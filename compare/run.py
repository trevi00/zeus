"""Independent reference/target comparison runner (REBUILD-DESIGN-v2 §5.1, §5.2, §5.3 S0).

Layer: harness (never shipped); standard library only. Usage from the worktree root:

    python compare/run.py check-tree          # S0 check 1: reference bytes, allowed paths, no secrets
    python compare/run.py prepare             # build the reference wheel from `git archive SOURCE`
    python compare/run.py run                 # run every scenario; compare with committed goldens
    python compare/run.py run --record        # reference-only: (re)write reference goldens

The reference environment is built from the SOURCE archive wheel, never from the working tree;
its package-file digest must equal `compare/baseline.json`. Each driver runs as a separate process
of its own environment with the R-P child environment and, where bwrap is available, without
network and with tmpfs over credential directories. The target side of every scenario stays
`pending` until a target driver exists: nothing is reported green without a target run.
Exit: 0 all reference results equal their goldens (and every present target equal too), 1 a
difference or failure, 2 usage.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

COMPARE = Path(__file__).resolve().parent
ROOT = COMPARE.parent
sys.path.insert(0, str(COMPARE / "guard"))
import provider_guard  # noqa: E402

BASELINE = json.loads((COMPARE / "baseline.json").read_text(encoding="utf-8"))
SOURCE_COMMIT = BASELINE["source"]["commit"]
SCRATCH = Path(os.environ.get("ZEUS_REBUILD_SCRATCH")
               or Path(tempfile.gettempdir()) / "zeus-rebuild-001").resolve()
SECRET_SHAPES = [re.compile(p) for p in (
    r"[a-z]+://[^\s/@:\"']+:[^\s/@\"']+@",           # URL with a password in its userinfo
    r"sk-ant-[A-Za-z0-9_-]{8,}", r"sk-[A-Za-z0-9]{32,}", r"gh[pousr]_[A-Za-z0-9]{20,}",
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----")]


def git(*args: str, cwd: Path = ROOT, text: bool = True):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=text).stdout


def check_tree() -> dict:
    """Reference bytes unchanged; only allowed paths changed; no credential-shaped strings added."""
    allowed = BASELINE["layout"]["allowed_changed_paths"]
    excludes = [f":(exclude){a.rstrip('/')}" for a in allowed]
    unchanged = subprocess.run(["git", "diff", "--quiet", SOURCE_COMMIT, "--", ".", *excludes],
                               cwd=ROOT).returncode == 0
    # The docs index and the design SSOT may only gain a link/pointer line (§3.1).
    additions_only = {}
    for path, limit in BASELINE["layout"]["additions_only"].items():
        numstat = git("diff", "--numstat", SOURCE_COMMIT, "--", path).split()
        added, deleted = (int(numstat[0]), int(numstat[1])) if numstat else (0, 0)
        additions_only[path] = {"added": added, "deleted": deleted,
                                "ok": deleted == 0 and added <= limit}
    changed = [p for p in git("diff", "--name-only", SOURCE_COMMIT, "--").splitlines() if p]
    changed += [p for p in git("ls-files", "--others", "--exclude-standard").splitlines() if p]
    outside = sorted(p for p in set(changed)
                     if not any(p == a or p.startswith(a.rstrip("/") + "/") for a in allowed))
    shaped = []
    for path in sorted(set(changed)):
        file = ROOT / path
        if not file.is_file():
            continue
        text = file.read_text(encoding="utf-8", errors="replace")
        for pattern in SECRET_SHAPES:
            if pattern.search(text):
                shaped.append({"path": path, "pattern": pattern.pattern})
    head_tree = git("rev-parse", f"{SOURCE_COMMIT}^{{tree}}").strip()
    return {"source_commit": SOURCE_COMMIT, "source_tree": head_tree,
            "source_tree_matches_baseline": head_tree == BASELINE["source"]["tree"],
            "reference_paths_unchanged": unchanged, "changed_paths": len(set(changed)),
            "changed_outside_allowed": outside, "credential_shaped_strings": shaped,
            "additions_only": additions_only,
            "ok": unchanged and not outside and not shaped
            and all(v["ok"] for v in additions_only.values())
            and head_tree == BASELINE["source"]["tree"]}


def prepare() -> dict:
    """Build the reference wheel from the SOURCE archive and install it into its own venv."""
    source, dist, venv = SCRATCH / "source", SCRATCH / "dist", SCRATCH / "venv-ref"
    for path in (source, dist):
        shutil.rmtree(path, ignore_errors=True)
        path.mkdir(parents=True)
    archive = subprocess.run(["git", "archive", SOURCE_COMMIT], cwd=ROOT, check=True,
                             capture_output=True).stdout
    subprocess.run(["tar", "-x", "-C", str(source)], input=archive, check=True)
    uv = shutil.which("uv") or sys.exit("uv is required to build the reference wheel")
    subprocess.run([uv, "build", "--wheel", "--out-dir", str(dist)], cwd=source, check=True,
                   capture_output=True)
    wheel = next(dist.glob("*.whl"))
    expected = BASELINE["source"]["reference_wheel"]
    facts = {"wheel": wheel.name, "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest()}
    requirements = SCRATCH / "ref-requirements.txt"
    requirements.write_text(subprocess.run(
        [uv, "export", "--frozen", "--no-dev", "--no-emit-project", "--no-hashes", "--format",
         "requirements.txt", "-q"], cwd=source, check=True, capture_output=True, text=True).stdout)
    python = venv / "bin" / "python"
    if not python.exists():
        subprocess.run([uv, "venv", "-q", "--python", BASELINE["environments"]["python"], str(venv)],
                       check=True)
    subprocess.run([uv, "pip", "install", "-q", "--python", str(python), "-r", str(requirements)],
                   check=True)
    subprocess.run([uv, "pip", "install", "-q", "--python", str(python), "--no-deps", "--reinstall",
                    str(wheel)], check=True)
    with zipfile.ZipFile(wheel) as archive_file:
        record = next(n for n in archive_file.namelist() if n.endswith(".dist-info/RECORD"))
        facts["wheel_record_sha256"] = hashlib.sha256(archive_file.read(record)).hexdigest()
    facts["wheel_sha256_matches_baseline"] = facts["wheel_sha256"] == expected["sha256"]
    facts["wheel_record_matches_baseline"] = (facts["wheel_record_sha256"]
                                              == expected["wheel_record_sha256"])
    return facts


def scenarios() -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8"))
            for p in sorted((COMPARE / "scenarios").glob("*.json"))]


def run_driver(python: Path, driver: Path, work: Path, extra_env: dict, use_bwrap: bool) -> dict:
    env = provider_guard.child_environment(work / "env", extra=extra_env)
    argv = [str(python), "-B", str(driver)]
    if use_bwrap:
        argv = provider_guard.bwrap_prefix([work]) + argv
    proc = subprocess.run(argv, cwd=str(work), env=env, capture_output=True, text=True, timeout=900)
    if proc.returncode != 0:
        tail = proc.stderr.strip().splitlines()[-5:]
        return {"error": f"driver exit {proc.returncode}", "stderr_tail": tail}
    return json.loads(proc.stdout.strip().splitlines()[-1])


def run(record: bool, use_bwrap: bool, only: list[str]) -> tuple[dict, bool]:
    python = SCRATCH / "venv-ref" / "bin" / "python"
    if not python.exists():
        sys.exit("reference venv missing: run `python compare/run.py prepare` first")
    expected = BASELINE["source"]["reference_wheel"]
    report, ok = {"bwrap": use_bwrap, "scenarios": {}}, True
    for scenario in scenarios():
        family = scenario["family"]
        if only and family not in only:
            continue
        with tempfile.TemporaryDirectory(prefix="zeus-s0-run-", dir=SCRATCH) as raw:
            work = Path(raw)
            result = run_driver(python, COMPARE / scenario["reference_driver"], work,
                                {"ZEUS_REBUILD_SOURCE_ROOT": str(SCRATCH / "source")}, use_bwrap)
        row = {"slice": scenario["slice"]}
        if "error" in result:
            row.update(reference="error", detail=result)
            ok = False
        else:
            origin = result["origin"]
            origin_ok = (origin.get("package_files_digest") == expected["package_files_digest"]
                         and origin.get("package_files") == expected["package_files"])
            golden_path = COMPARE / scenario["golden"]
            if record:
                golden_path.write_text(json.dumps(result["result"], sort_keys=True, indent=1,
                                                  ensure_ascii=False) + "\n", encoding="utf-8")
            golden = json.loads(golden_path.read_text(encoding="utf-8")) if golden_path.exists() else None
            equal = golden == result["result"]
            row.update(reference="equal" if equal else "DIFFERENT", origin_ok=origin_ok,
                       origin={k: origin.get(k) for k in ("modules_checked", "python", "package_files",
                                                           "package_files_digest")})
            ok = ok and equal and origin_ok
        target = scenario.get("target_driver")
        if target and (COMPARE / target).exists():
            row["target"] = "not wired in S0"
            ok = False
        else:
            row["target"] = f"pending: no target implementation before {scenario['slice']}"
        report["scenarios"][family] = row
    return report, ok


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check-tree")
    sub.add_parser("prepare")
    run_cmd = sub.add_parser("run")
    run_cmd.add_argument("--record", action="store_true", help="write reference goldens")
    run_cmd.add_argument("--no-bwrap", action="store_true")
    run_cmd.add_argument("--only", action="append", default=[])
    args = parser.parse_args(argv)
    if args.command == "check-tree":
        report = check_tree()
        ok = report["ok"]
    elif args.command == "prepare":
        report = prepare()
        # The wheel sha256 depends on the unpinned build backend; the RECORD rows are the identity.
        ok = report["wheel_record_matches_baseline"]
    else:
        use_bwrap = provider_guard.bwrap_available() and not args.no_bwrap
        SCRATCH.mkdir(parents=True, exist_ok=True)
        report, ok = run(args.record, use_bwrap, args.only)
    print(json.dumps({"command": args.command, "ok": ok, **report}, indent=1, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
