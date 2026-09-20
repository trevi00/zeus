"""Research program adapters (INV-RESEARCH-PROGRAM-001): live collection through the existing
`ResearchSources`, local candidate verification through the dge Git verifier, the detached capture
commit, the local JSONL event log, the bounded report and the finite tick runner that connects them
to the existing `autonomous_cli.run` council.

Nothing here retries, repairs, merges or deploys. The store is touched only through the application
state machine, one transaction per recorded fact, never across a fetch, a Git command or the council.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

from codex_harness.adapters.commands import run_process
from codex_harness.adapters.dge_cli import verify_sources
from codex_harness.adapters.operation_cli import GitSource
from codex_harness.application.autonomous import BUCKET as RUNS
from codex_harness.application.dge import DgeRefused
from codex_harness.application.research_program import ResearchProgram
from codex_harness.domain.autonomous import manifest_digest
from codex_harness.domain.model import ContractError, canonical, digest, utcnow
from codex_harness.domain.operation import safe_relative_path
from codex_harness.domain.research_investigations import SOURCE as INVESTIGATION
from codex_harness.domain.research_program import (
    CAPTURE_ROOT,
    EXTERNAL_SOURCES,
    ProgramRefused,
    bounded_text,
    capture_path,
    capture_ref,
    council_result,
    derive_manifest,
    normalize_url,
    run_id,
    snapshot_document,
)

CAPTURE_AUTHOR = {"GIT_AUTHOR_NAME": "Zeus Research Program", "GIT_AUTHOR_EMAIL": "research-program@localhost",
                  "GIT_COMMITTER_NAME": "Zeus Research Program", "GIT_COMMITTER_EMAIL": "research-program@localhost"}
GIT_TIMEOUT = 60
MAX_SNAPSHOT_BYTES = 64 * 1024
CATEGORIES = ("general", "development", "operations")


class CaptureError(ContractError):
    def __init__(self, reason_code: str):
        super().__init__("capture refused: " + reason_code)
        self.reason_code = reason_code


# ----- collection --------------------------------------------------------------------------------------
def collect_live(sources) -> tuple[dict, list]:
    """BOTH feeds through ResearchSources, each recorded ok/unavailable independently with the
    exception TYPE only. Raw bodies stay in the artifact store; items are bounded title/summary."""
    status, items = {}, []
    for name in EXTERNAL_SOURCES:
        try:
            result = sources.collect(name)
        except Exception as exc:  # network, parse or size failures: a code, never the text
            status[name] = {"status": "unavailable", "code": type(exc).__name__, "artifact": None, "fetched_at": None, "items": None}
            continue
        entries = []
        for item in result["items"]:
            url = normalize_url(item.get("url"))
            if url is None:
                continue
            title, summary = bounded_text(item.get("title"), 400), bounded_text(item.get("summary"), 1500)
            entries.append({"source": name, "identity": url, "url": url, "title": title, "summary": summary,
                            "content_sha256": digest({"title": title, "summary": summary})})
        status[name] = {"status": "ok", "code": None, "artifact": result["artifact"], "fetched_at": result["fetched_at"],
                        "items": len(entries)}
        items.extend(entries)
    return status, items


def collect_local(config: dict, source) -> tuple[dict, list]:
    """Owner-authorized local rows re-verified at config.base through the dge verifier (regular
    blob, exact digest); a failed verification makes the local source unavailable with its code."""
    rows = config["local_candidates"]
    if not rows:
        return {"status": "ok", "code": None, "artifact": None, "fetched_at": None, "items": 0}, []
    try:
        bound = verify_sources({"base_revision": config["base_revision"], "sources": rows}, source)
    except DgeRefused as exc:
        return {"status": "unavailable", "code": exc.reason_code, "artifact": None, "fetched_at": None, "items": None}, []
    except Exception as exc:
        return {"status": "unavailable", "code": type(exc).__name__, "artifact": None, "fetched_at": None, "items": None}, []
    verified = {b["id"]: b for b in bound}
    items = [{"source": "local", "identity": row["path"], "id": row["id"], "path": row["path"], "sha256": row["sha256"],
              "topic": row["topic"], "title": row["path"], "summary": row["rationale"], "url": None,
              "content_sha256": verified[row["id"]]["sha256"]} for row in rows]
    return {"status": "ok", "code": None, "artifact": None, "fetched_at": None, "items": len(items)}, items


# ----- capture commit ------------------------------------------------------------------------------------
class GitCapture:
    """A detached capture commit on top of the immutable base in the SAME object database: temporary
    index, hash-object, update-index, write-tree, commit-tree, then one new ref. The checkout, its
    index and HEAD are never read or moved; only the owned temporary index is cleaned up."""

    def __init__(self, repository, timeout: int = GIT_TIMEOUT):
        self.repository, self.timeout = str(Path(repository).resolve()), timeout

    def _git(self, *args, env=None, input_text=None):
        result = run_process(["git", "-C", self.repository, *args], timeout=self.timeout, env=env, input_text=input_text)
        return result.returncode, result.stdout.strip()

    def capture(self, base: str, path: str, body: str, ref: str) -> dict:
        if not (safe_relative_path(path) and path.startswith(CAPTURE_ROOT + "/") and path.endswith(".json")):
            raise CaptureError("capture_path_invalid")
        if not ref.startswith("refs/zeus/research/") or any(s in {"", ".", ".."} or s.endswith(".lock") for s in ref.split("/")):
            raise CaptureError("capture_ref_invalid")
        data = body.encode("utf-8")
        if len(data) > MAX_SNAPSHOT_BYTES:
            raise CaptureError("capture_too_large")
        expected_blob = hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()
        code, _ = self._git("cat-file", "-e", base + "^{commit}")
        if code:
            raise CaptureError("base_revision_missing")
        code, listing = self._git("ls-tree", base, "--", path)
        if code or listing:
            raise CaptureError("capture_path_exists")
        code, _ = self._git("show-ref", "--verify", "--quiet", ref)
        if code == 0:
            raise CaptureError("capture_ref_exists")
        with tempfile.TemporaryDirectory(prefix="zeus-capture-") as directory:
            env = {**os.environ, "GIT_INDEX_FILE": str(Path(directory) / "index"), **CAPTURE_AUTHOR}
            code, _ = self._git("read-tree", base, env=env)
            if code:
                raise CaptureError("capture_read_tree_failed")
            # review001 R3: exact UTF-8 bytes. A text-mode stdin pipe rewrites LF on Windows, so the
            # body goes through an owned binary temp file and `--no-filters` (no attribute/eol
            # conversion); the content-addressed blob id proves the stored bytes are `data`.
            blob = self._hash_blob(Path(directory) / "snapshot.bin", data, env)
            if blob != expected_blob:
                raise CaptureError("capture_blob_mismatch")
            code, _ = self._git("update-index", "--add", "--cacheinfo", "100644," + blob + "," + path, env=env)
            if code:
                raise CaptureError("capture_index_failed")
            code, tree = self._git("write-tree", env=env)
            if code or len(tree) != 40:
                raise CaptureError("capture_tree_failed")
            message = "zeus research capture " + path
            code, commit = self._git("commit-tree", tree, "-p", base, "-m", message, env=env)
            if code or len(commit) != 40:
                raise CaptureError("capture_commit_failed")
        # Binary readback through the same reader the dge verifier uses, BEFORE the ref exists.
        mode, stored = GitSource(self.repository).blob(commit, path)
        if mode != "100644" or stored != data:
            raise CaptureError("capture_readback_mismatch")
        # The empty old value makes the ref creation refuse any ref that appeared meanwhile.
        code, _ = self._git("update-ref", ref, commit, "")
        if code:
            raise CaptureError("capture_ref_failed")
        return {"revision": commit, "tree": tree, "blob": blob, "ref": ref, "path": path,
                "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}

    def _hash_blob(self, file: Path, data: bytes, env: dict) -> str:
        file.write_bytes(data)
        code, blob = self._git("hash-object", "-w", "--no-filters", "--", str(file), env=env)
        if code or len(blob) != 40:
            raise CaptureError("capture_blob_failed")
        return blob


# ----- event log and report ---------------------------------------------------------------------------------
class EventLog:
    """Explicit local JSONL log with three categories; identifiers, counts and codes only."""

    def __init__(self, root: Path, program_id: str):
        self.path = Path(root) / "research-program" / program_id / "events.jsonl"

    def emit(self, category: str, event: str, cycle=None, **attributes) -> None:
        if category not in CATEGORIES:
            raise ContractError("Unknown research program event category")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        record = {"at": utcnow(), "category": category, "event": event, "cycle": cycle, "attributes": attributes}
        with self.path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(canonical(record) + "\n")


def render_report(view: dict) -> str:
    """Bounded Markdown from the store projection: real counts, the configured stage chain and per
    cycle what was actually observed. No model-generated facts."""
    lines = ["# Research program " + view["id"], "",
             "State: " + view["state"] + "; cycles " + str(view["cycles"]["completed"]) + "/" + str(view["cycles"]["max"])
             + "; dispatched councils " + str(view["adoptions"]["dispatched"]) + "/" + str(view["adoptions"]["max"])
             + "; stop reason: " + str(view["stop_reason"]) + "; blocked reason: " + str(view["blocked_reason"]), "",
             "Configured stages (authorization, not observed success):", "",
             "    sources(local + github + geeknews) -> dedup/relevance -> select <=1 -> capture commit"
             " -> autonomous:2 council (research -> DBA -> leads -> conductor -> implement -> review -> promotion) -> result", "",
             "Candidates: total " + str(view["candidates"]["total"]) + ", eligible " + str(view["candidates"]["eligible"])
             + ", claimed " + str(view["candidates"]["claimed"]) + ", ignored " + str(view["candidates"]["ignored"]), "",
             # Dispatch counts are not acceptance: claimed/dispatched work is still in flight and an
             # accepted council is still not an owner disposition, a fixed incident or a merge.
             "Investigation dispatches (claim and council outcome only, never an owner disposition): "
             + ", ".join(name + " " + str(count) for name, count in view["investigations"].items()), "",
             "## Observed cycles", ""]
    for cycle in view["cycle_receipts"]:
        sources = cycle.get("sources") or {}
        source_text = ", ".join(name + "=" + str(sources.get(name, {}).get("status", "missing"))
                                + ("(" + str(sources[name].get("code")) + ")" if sources.get(name, {}).get("code") else "")
                                for name in ("local", "github", "geeknews"))
        counts, selection = cycle.get("counts") or {}, cycle.get("selection") or {}
        capture, council = cycle.get("capture") or {}, cycle.get("council") or {}
        bridge = cycle.get("investigations")
        investigation_text = ("" if bridge is None else
                              "; investigations scanned " + str(bridge["counts"]["scanned"]) + " eligible "
                              + str(bridge["counts"]["eligible"]) + " new " + str(bridge["new"]) + " ineligible "
                              + str(bridge["ineligible"]) + " claimed " + str(bridge["claimed"])
                              + "; dispatch result " + str(bridge["result"]) + " (reported "
                              + str(bridge["reported_result"]) + ")")
        lines.append("- cycle " + str(cycle["number"]) + " [" + cycle["status"] + "]: sources " + source_text
                     + "; discovered " + str(counts.get("discovered")) + " new " + str(counts.get("new")) + " duplicate "
                     + str(counts.get("duplicate")) + " ignored " + str(counts.get("ignored")) + " selected " + str(counts.get("selected"))
                     + "; selection " + str(selection.get("candidate")) + " (" + str(selection.get("reason")) + ")"
                     + "; capture " + str(capture.get("revision")) + "; council " + str(council.get("run_id")) + " -> "
                     + str(council.get("status")) + " (" + str(council.get("reason_code")) + "); result " + str(cycle.get("result"))
                     + "; failure " + str((cycle.get("failure") or {}).get("stage")) + "/" + str((cycle.get("failure") or {}).get("code"))
                     + investigation_text)
    lines += ["", "Result vocabulary: accepted/rejected/failed/unknown come from the authoritative autonomous_runs row;",
              "a rejected council stays rejected; unknown is distinct from missing and from zero.", ""]
    return "\n".join(lines)


def write_report(root: Path, view: dict) -> Path:
    path = Path(root) / "research-program" / view["id"] / "report.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_report(view), encoding="utf-8", newline="\n")
    return path


# ----- runner -------------------------------------------------------------------------------------------------
class ProgramRunner:
    """One finite tick: reserve -> collect (read-only, no models) -> record -> if selected: snapshot,
    capture commit, derived manifest, council start record, existing council, authoritative row read,
    result record. `council(service, args)` is `autonomous_cli.run` in production; tests inject a
    labelled stand-in. `github_detail(url)` is optional and its failure is recorded unknown."""

    def __init__(self, service, programs: ResearchProgram, sources, git_source, capture: GitCapture, budget, artifacts,
                 runtime: Path, council, github_detail=None, clock=utcnow, repository: str = ""):
        self.service, self.programs, self.sources, self.git_source = service, programs, sources, git_source
        self.capture, self.budget, self.artifacts, self.runtime = capture, budget, artifacts, Path(runtime)
        self.council, self.github_detail, self.clock = council, github_detail, clock
        # review001 R1: the identity digest of the CURRENT repository root; compared with the
        # registered identity inside the reservation transaction, before any tick effect.
        self.repository = repository

    def run(self, program_id: str, ticks: int) -> dict:
        if type(ticks) is not int or ticks < 1:
            raise ProgramRefused("ticks_invalid")
        receipts = []
        for _ in range(ticks):
            receipt = self.tick(program_id)
            receipts.append(receipt)
            if not receipt.get("reserved") or receipt.get("result") in {"failed", "unknown"} or receipt.get("failure"):
                break
        return {"id": program_id, "requested_ticks": ticks, "ticks": receipts}

    def tick(self, program_id: str) -> dict:
        log = EventLog(self.runtime, program_id)
        reservation = self.programs.reserve_cycle(program_id, self.repository)  # raises repository_mismatch first
        if not reservation["reserved"]:
            log.emit("general", "tick_skipped", reason=reservation["reason"], state=reservation["state"])
            return {"reserved": False, "reason": reservation["reason"], "state": reservation["state"]}
        cycle, config, owner = reservation["cycle"], reservation["config"], reservation["cycle"]["owner"]
        number = cycle["number"]
        log.emit("general", "tick_started", cycle=number)
        # ----- discovery: read-only, no model calls, no open transaction -----
        local_status, local_items = collect_local(config, self.git_source)
        live_status, live_items = collect_live(self.sources)
        sources = {"local": local_status, **live_status}
        degraded = [name for name, row in sources.items() if row["status"] != "ok"]
        try:
            counts = self.budget.counts()
        except Exception as exc:
            counts = {"unreadable": type(exc).__name__}
        recorded = self.programs.record_collection(cycle["id"], owner, sources, local_items + live_items, counts)
        cycle, candidate = recorded["cycle"], recorded["candidate"]
        log.emit("development", "collection_recorded", cycle=number, counts=cycle["counts"], degraded=degraded,
                 selection=cycle["selection"], headroom=cycle["budget"]["headroom"])
        bridge = cycle.get("investigations")
        if bridge is not None:   # opt-in bridge only: identifiers and bounded counts, no payload
            log.emit("development", "investigations_scanned", cycle=number, counts=bridge["counts"],
                     new=bridge["new"], ineligible=bridge["ineligible"])
            if bridge["claimed"] is not None:
                log.emit("general", "investigation_claimed", cycle=number, investigation=bridge["claimed"],
                         candidate=cycle["selection"]["candidate"])
        if degraded:
            log.emit("operations", "source_degraded", cycle=number, sources={n: sources[n]["code"] for n in degraded})
        if candidate is None:
            self.programs.complete_cycle(cycle["id"], owner)
            return self._finish(program_id, log, number, {"reserved": True, "cycle": cycle["id"], "selected": None,
                                                          "reason": cycle["selection"]["reason"], "degraded": degraded, "result": None})
        # ----- evidence capture -----
        claim = {"investigation": candidate["investigation"]} if candidate["source"] == INVESTIGATION else {}
        try:
            capture = self._capture(config, number, candidate, sources)
        except (CaptureError, ContractError) as exc:
            code = getattr(exc, "reason_code", "contract_refused")
            self.programs.fail_cycle(cycle["id"], owner, "capture", code)
            log.emit("operations", "cycle_failed", cycle=number, stage="capture", code=code, **claim)
            return self._finish(program_id, log, number, {"reserved": True, "cycle": cycle["id"], "selected": candidate["id"],
                                                          "failure": {"stage": "capture", "code": code}, "result": None, **claim})
        except Exception as exc:
            self.programs.fail_cycle(cycle["id"], owner, "capture", type(exc).__name__)
            log.emit("operations", "cycle_failed", cycle=number, stage="capture", code=type(exc).__name__, **claim)
            return self._finish(program_id, log, number, {"reserved": True, "cycle": cycle["id"], "selected": candidate["id"],
                                                          "failure": {"stage": "capture", "code": type(exc).__name__},
                                                          "result": None, **claim})
        # ----- pre-provider preparation (review001 R2): every stage tracked; a failure here is
        # recorded as a blocked cycle with the capture reference retained, and no council runs -----
        stage = "capture_record"
        try:
            self.programs.record_capture(cycle["id"], owner, capture)
            log.emit("development", "capture_recorded", cycle=number, revision=capture["revision"], ref=capture["ref"], **claim)
            stage = "manifest_derive"
            manifest = derive_manifest(config, number, capture["revision"], candidate)
            sha = manifest_digest(manifest)
            stage = "manifest_artifact"
            stored = self.artifacts.put(canonical(manifest), "research-program:" + program_id + ":" + str(number))
            stage = "manifest_file"
            path = self.runtime / "research-program" / program_id / "manifests" / (run_id(program_id, number) + ".json")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(canonical(manifest), encoding="utf-8", newline="\n")
            stage = "council_start"
            self.programs.record_council_start(cycle["id"], owner, manifest["id"], sha, stored["ref"])
        except Exception as exc:
            return self._fail_before_council(program_id, log, cycle, owner, capture, stage, exc, claim)
        log.emit("development", "council_started", cycle=number, run_id=manifest["id"], manifest_sha256=sha, **claim)
        error = None
        try:
            self.council(self.service, SimpleNamespace(file=path))
        except Exception as exc:  # stdout/return value are never authority; the run row is read below
            error = type(exc).__name__
        with self.service.store.transaction() as tx:
            row = tx.get(RUNS, manifest["id"])
        verdict = council_result(manifest["id"], sha, row)
        if error is not None and row is None:
            verdict = {"result": "failed", "reason_code": "council_refused:" + error, "row_status": None}
        self.programs.record_council_result(cycle["id"], owner, verdict)
        category = "operations" if verdict["result"] in {"failed", "unknown"} else "development"
        log.emit(category, "council_result", cycle=number, run_id=manifest["id"], **verdict, **claim)
        dispatch = self._dispatch_outcome(candidate)
        if dispatch is not None:   # the store's own authoritative dispatch outcome, never the verdict text
            log.emit(category, "investigation_result", cycle=number, run_id=manifest["id"], **dispatch)
        return self._finish(program_id, log, number, {"reserved": True, "cycle": cycle["id"], "selected": candidate["id"],
                                                      "run_id": manifest["id"], "capture": capture["revision"], **verdict,
                                                      **claim})

    def _dispatch_outcome(self, candidate) -> dict | None:
        """The recorded dispatch row of THIS claim, read back for the log; identifiers and codes only."""
        if candidate["source"] != INVESTIGATION:
            return None
        row = next((d for d in self.programs.dispatches() if d["investigation"] == candidate["investigation"]), None)
        return None if row is None else {k: row[k] for k in ("investigation", "state", "result", "result_reason",
                                                             "reported_result", "row_status")}

    def _fail_before_council(self, program_id, log, cycle, owner, capture, stage, exc, claim=None) -> dict:
        """Zero council calls. If the store still records the failure, the cycle is counted, the
        program blocked and the claim plus capture reference kept. If recording itself fails the
        cycle stays owned (busy) and the receipt says so: no durable receipt is claimed."""
        code = getattr(exc, "reason_code", None) or type(exc).__name__
        number, claim = cycle["number"], claim or {}
        retained = {"revision": capture["revision"], "ref": capture["ref"], "path": capture["path"], "artifact": capture["artifact"]}
        receipt = {"reserved": True, "cycle": cycle["id"], "selected": capture["candidate"], "result": None,
                   "failure": {"stage": stage, "code": code, "recorded": True, "capture": retained}, **claim}
        try:
            self.programs.fail_cycle(cycle["id"], owner, stage, code, recovery={"capture": retained})
        except Exception as record_exc:
            receipt["failure"].update(recorded=False, record_code=type(record_exc).__name__)
            try:
                log.emit("operations", "cycle_failure_unrecorded", cycle=number, stage=stage, code=code,
                         record_code=type(record_exc).__name__, capture=capture["revision"], **claim)
            except OSError:
                pass
            return {**receipt, "state": "unknown", "stop_reason": None, "report": None}
        log.emit("operations", "cycle_failed", cycle=number, stage=stage, code=code, capture=capture["revision"], **claim)
        return self._finish(program_id, log, number, receipt)

    def _capture(self, config, number, candidate, sources) -> dict:
        local_sha = None
        if candidate["source"] == "local":
            mode, data = self.git_source.blob(config["base_revision"], candidate["path"])
            if mode != "100644":
                raise CaptureError("local_source_not_regular")
            local_sha = hashlib.sha256(data).hexdigest()
            if local_sha != candidate["sha256"]:
                raise CaptureError("local_source_digest_mismatch")
        detail = {"status": "not_requested"}
        if candidate["source"] == "github" and self.github_detail is not None:
            try:
                fetched = self.github_detail(candidate["url"])
                detail = {"status": "ok", **{k: fetched.get(k) for k in ("revision", "readme_ref", "license", "archived", "pushed_at",
                                                                          "default_branch", "fetched_at")}}
            except Exception as exc:
                detail = {"status": "unknown", "code": type(exc).__name__}
        document = snapshot_document(program_id=config["id"], number=number, base_revision=config["base_revision"],
                                     fetched_at=self.clock(), candidate=candidate, sources=sources,
                                     local_bytes_sha256=local_sha, github_detail=detail)
        body = json.dumps(document, sort_keys=True, ensure_ascii=False, indent=1) + "\n"
        receipt = self.artifacts.put(body, "research-capture:" + config["id"] + ":" + str(number))
        captured = self.capture.capture(config["base_revision"], capture_path(config["id"], number), body,
                                        capture_ref(config["id"], number))
        return {**captured, "artifact": receipt["ref"], "candidate": candidate["id"]}

    def _finish(self, program_id, log, number, receipt) -> dict:
        view = self.programs.status(program_id)
        try:
            report = write_report(self.runtime, view)
        except OSError as exc:
            log.emit("operations", "report_unwritten", cycle=number, code=type(exc).__name__)
            report = None
        log.emit("general", "tick_finished", cycle=number, state=view["state"], cycles=view["cycles"], adoptions=view["adoptions"])
        return {**receipt, "state": view["state"], "stop_reason": view["stop_reason"], "report": None if report is None else str(report)}


__all__ = ["CaptureError", "EventLog", "GitCapture", "ProgramRunner", "collect_live", "collect_local", "render_report",
           "write_report"]
