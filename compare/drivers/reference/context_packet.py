"""Reference driver: retained context packet artifacts and their bindings (REBUILD-DESIGN-v2 §2.7, F4).

Scenario family `effects.context_packet`. Runs M7 `Executor.execute_one('worker:github')` for a
research task with an injected fixture transport (the in-process `AppServer` name is replaced in
this driver process; no provider exists), a fake clock, deterministic ids and a fixed disposable
workspace root (injection, so no ref needs a mask). It captures, without printing any payload:
- every `context:<key>` artifact: ref, byte length, sha256 of the bytes, field names, compiler
  version, evidence/omitted counts and whether `manifest_hash` recomputes from the stored packet;
- the bindings: the execution record's `context_ref`, the observation/checkpoint `context_ref`
  and `evidence_refs`, compared by equality with the stored refs;
- whether the delivered prompt equals `ContextPacket.render()` of the stored packet (digest only).
The interpreter path M7 embeds in the packet is injected as a fixed placeholder, so the refs do not
depend on the host (a digest never covers a masked value).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "harness"))

import driver  # noqa: E402

driver.start("reference")

import hashlib  # noqa: E402
import json  # noqa: E402
import shutil  # noqa: E402
from types import SimpleNamespace  # noqa: E402

import determinism  # noqa: E402

from codex_harness.adapters import executor as executor_module  # noqa: E402
from codex_harness.adapters.artifacts import FileArtifacts  # noqa: E402
from codex_harness.adapters.executor import Executor  # noqa: E402
from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application import execution_time, workflow  # noqa: E402,F401
from codex_harness.application.service import Harness  # noqa: E402
from codex_harness.bootstrap import organization  # noqa: E402
from codex_harness.domain.model import ContextPacket, canonical, digest, envelope  # noqa: E402

ROOT = Path("/tmp/zeus-rebuild-s0-context-packet")
MARKER = ".zeus-rebuild-s0-disposable"
URL = "https://github.com/owner/repo"
REV = "a" * 40
CLOCK, IDS = determinism.FakeClock(), determinism.FakeIds()
determinism.install(CLOCK, IDS, constants={
    "codex_harness.application.execution_time": {"DOMAIN": "00000000-0000-4000-8000-00000000c0c0"}})


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def fresh_root() -> Path:
    if ROOT.exists():
        if not (ROOT / MARKER).exists():
            raise SystemExit(f"{ROOT} exists and is not a labelled disposable S0 root")
        shutil.rmtree(ROOT)
    ROOT.mkdir(parents=True)
    (ROOT / MARKER).write_text("disposable S0 context-packet workspace\n", encoding="utf-8")
    return ROOT


class RecordingArtifacts(FileArtifacts):
    def __init__(self, root):
        super().__init__(root)
        self.puts = []

    def put(self, body, source, lock_timeout=30):
        ref = super().put(body, source, lock_timeout)
        self.puts.append({"source": source, "ref": ref["ref"], "bytes": len(body.encode("utf-8"))})
        return ref


def main() -> None:
    root = fresh_root()
    # Injection (R-D): M7 writes `sys.executable` (the artifact-reader argv) and its resolved path
    # (the review interpreter) into the retained packet, so the ref would cover a host path. The
    # driver names a fixed placeholder file instead; it is never executed in this scenario.
    interpreter = root / "bin" / "python"
    interpreter.parent.mkdir()
    interpreter.write_text("#!/bin/sh\nexit 97\n", encoding="utf-8")
    interpreter.chmod(0o755)
    sys.executable = str(interpreter)
    service = Harness(MemoryStore(), organization())
    artifacts = RecordingArtifacts(str(root / "artifacts"))
    config = {"shortlist": {"source_url": URL},
              "final": {"source_url": URL, "source_revision": REV, "title": "Improve",
                        "objective": "Improve", "evidence": "README", "acceptance_criteria": []}}
    collection = {"artifact": artifacts.put("collected source", "fixture")["ref"],
                  "items": [{"url": URL, "summary": "fixture summary " * 40}]}
    readme = artifacts.put("README fixture " * 200, "fixture")["ref"]
    prompts = []

    class FixtureTransport:
        def __init__(self, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def run(self, prompt, cwd, schema, *args, **kw):
            prompts.append(sha(prompt))
            packet = json.loads(prompt)
            stage = packet["required"].get("research_context", {}).get("stage", "final")
            event = {"method": "item/completed", "params": {"item": {"id": stage, "type": "command"}}}
            kw["on_event"](event)
            CLOCK.advance(1)
            return {"answer": config[stage], "events": [event], "thread_id": stage,
                    "usage": {"totalTokens": 123}, "rotate": False, "interrupted": False}

    executor_module.AppServer = FixtureTransport
    executor = Executor(service, SimpleNamespace(repository=root, _git=lambda *a, **kw: "harness"),
                        artifacts, research=SimpleNamespace(
                            collect=lambda source, *, intent: collection,
                            github_detail=lambda url: {"url": URL, "revision": REV, "readme_ref": readme}))
    message = envelope("task.assign", "lead:research", "worker:github", "research",
                       {"source": "github", "intent": "user_request"}, "fixture")
    executor.workflow.submit(message)
    CLOCK.advance(1)
    completed = executor.execute_one("worker:github")
    result = completed["result"]

    packets = []
    for put in artifacts.puts:
        if not put["source"].startswith("context:"):
            continue
        body = artifacts._body(put["ref"])
        stored = json.loads(body)
        packet = ContextPacket(**stored)
        rendered = packet.render()
        recomputed = digest({"rendered": rendered, "omitted": packet.omitted,
                             "compiler": packet.compiler_version})
        packets.append({
            "source_label_prefix": "context:",
            "source_label_is_task_key": put["source"][len("context:"):] == stored["task_id"],
            "ref": put["ref"],
            "bytes": put["bytes"],
            "sha256_matches_ref": put["ref"] == "sha256:" + sha(body),
            "canonical_bytes": canonical(stored) == body,
            "fields": sorted(stored),
            "compiler_version": stored["compiler_version"],
            "evidence_ids": [item.get("id") for item in stored["evidence"]],
            "omitted_count": len(stored["omitted"]),
            "estimated_tokens_is_rendered_utf8_bytes": stored["estimated_tokens"] == len(rendered.encode()),
            "manifest_hash": stored["manifest_hash"],
            "manifest_hash_recomputes": recomputed == stored["manifest_hash"],
            "delivered_prompt_equals_render": sha(rendered) in prompts,
        })
    refs = {p["ref"] for p in packets}
    bindings = {}
    for name in ("execution_ref", "shortlist_execution_ref"):
        record = json.loads(artifacts._body(result[name]))
        bindings[name] = {"context_ref_is_stored_packet": record.get("context_ref") in refs,
                          "record_fields": sorted(record)}
    with service.store.transaction() as tx:
        rows = tx.records()
    bound = []
    for row in rows:
        text = canonical(row["body"])
        hits = sorted(ref for ref in refs if ref in text)
        if hits:
            bound.append({"bucket": row["bucket"], "refs": [sorted(refs).index(h) for h in hits]})
    out = {
        "status": completed["status"],
        "packets": packets,
        "execution_record_bindings": bindings,
        "store_rows_binding_context_refs": sorted(bound, key=lambda b: (b["bucket"], b["refs"])),
        "artifact_sources": sorted({p["source"].split(":", 1)[0] for p in artifacts.puts}),
        "provider_transport_calls": len(prompts),
    }
    shutil.rmtree(root)
    driver.finish("reference", "effects.context_packet", out)


if __name__ == "__main__":
    main()
