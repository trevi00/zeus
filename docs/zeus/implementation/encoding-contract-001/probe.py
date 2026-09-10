"""FA-001 reproduction: does a Zeus-launched Python child encode stdio as run_process decodes it?

Runs the current interpreter as an actual child through the real adapters. No database,
release flow, Codex or GitHub call is involved; the receipt covers the machine channel only.
Usage: uv run python docs/zeus/implementation/encoding-contract-001/probe.py [output.json]
"""
import hashlib
import json
import os
import platform
import sys
from pathlib import Path

from codex_harness.adapters import commands, verification
from codex_harness.adapters.commands import run_process

ROOT = Path(__file__).resolve().parents[4]
TEXT = "검증 — 완료"  # U+2014 is not representable in cp949.
CHILDREN = {
    # Same shape as the original cross-review probe: the child prints a literal.
    "literal": [sys.executable, "-X", "utf8=0", "-c",
                "import sys;print(sys.stdout.encoding,flush=True);print(%r,flush=True)" % TEXT],
    # Hook canary shape: the parent feeds stdin and reads the echo back.
    "roundtrip": [sys.executable, "-X", "utf8=0", "-c",
                  "import sys;print(sys.stdout.encoding,flush=True);print(sys.stdin.read(),flush=True)"]}
ENDPOINTS = {"database_url": "postgresql://probe", "redis_url": "redis://probe"}


def case(name, env, note):
    runs = {}
    for shape, argv in CHILDREN.items():
        result = run_process(argv, input_text=TEXT, env=env, timeout=60)
        expected = "utf-8\n" + TEXT + "\n"
        runs[shape] = {"argv": argv, "returncode": result.returncode, "stdout": result.stdout,
                       "stderr": result.stderr, "expected_stdout": expected,
                       "matches_expected": result.returncode == 0 and result.stdout == expected}
    return {"case": name, "note": note, "PYTHONIOENCODING": env.get("PYTHONIOENCODING"),
            "PYTHONUTF8": env.get("PYTHONUTF8"), "runs": runs}


def main():
    contract = getattr(commands, "python_channel_environment", None)
    adversarial = {**os.environ, "PYTHONIOENCODING": "cp949", "PYTHONUTF8": "0"}
    cases = [case("inherited_environment", dict(os.environ), "Parent environment as-is."),
             case("adversarial_cp949", adversarial, "Operator-set cp949 channel, failure control."),
             case("verification_environment", verification.verification_environment(ENDPOINTS, adversarial),
                  "Release pytest environment built from the adversarial parent.")]
    if contract:
        cases.append(case("python_channel_environment", contract(adversarial),
                          "Explicit machine-channel contract over the adversarial parent."))
    receipt = {"platform": sys.platform, "os": platform.platform(), "python": sys.version,
               "contract_present": contract is not None,
               "scope": "Actual native child process encoding only; no database, release, Codex or GitHub execution.",
               "source_hashes": {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in (
                   "src/codex_harness/adapters/commands.py", "src/codex_harness/adapters/verification.py",
                   "src/codex_harness/adapters/hooks.py")},
               "cases": cases}
    text = json.dumps(receipt, ensure_ascii=False, indent=2) + "\n"
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(text, encoding="utf-8")
    sys.stdout.buffer.write(text.encode("utf-8"))


if __name__ == "__main__":
    main()
