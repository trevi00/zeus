from __future__ import annotations

import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from codex_harness.adapters.commands import run_process
from codex_harness.adapters.configuration import compose_environment, runtime_dir
from codex_harness.adapters.hooks import NativeHooks
from codex_harness.adapters.verification import VerificationServices, verification_environment
from codex_harness.application.releases import Releases
from codex_harness.application.tickets import TicketSuperseded, ticket_binding
from codex_harness.application.workflow import Workflow
from codex_harness.domain.model import canonical, digest, require, utcnow
from codex_harness.domain.policy import POLICY


class ReleaseRunner:
    """Host-side canary controller, independent of the candidate's Codex process."""

    def __init__(self, service, git, artifacts, auth: str, auto_merge: bool = True, fence=None):
        self.service, self.git, self.artifacts = service, git, artifacts
        self.auth = Path(auth).resolve()
        self.auto_merge = auto_merge
        self.releases = Releases(service.store, service.org)
        self.fence = fence or (lambda: None)

    def _check(self, argv: list[str], cwd: str | None = None,
               timeout: int = POLICY.release_check_seconds, env=None) -> dict:
        self.fence()
        try:
            process = run_process(argv, cwd=cwd, timeout=timeout, env=env)
            self.fence()
            receipt = self.artifacts.put(canonical({"argv": argv, "exit_code": process.returncode,
                                         "stdout": process.stdout, "stderr": process.stderr}), "canary")
            unavailable = argv[0] == "docker" and any(text in process.stderr.lower() for text in (
                    "cannot connect to the docker daemon", "is the docker daemon running",
                    "error during connect", "failed to connect to the docker"))
            if argv[0] == "docker" and process.returncode and not unavailable:
                # Localized daemon diagnostics are not candidate execution evidence.
                server = run_process(["docker", "info", "--format", "{{.ServerVersion}}"], timeout=15)
                unavailable = server.returncode != 0
            return {"passed": process.returncode == 0, "evidence": receipt["ref"],
                    "outcome": "observation_error" if unavailable else "executed"}
        except (subprocess.TimeoutExpired, OSError) as exc:
            receipt = self.artifacts.put(str(exc), "canary-failure")
            return {"passed": False, "evidence": receipt["ref"], "outcome": "observation_error"}

    def run(self, release_id: str) -> dict:
        self.fence()
        # The queue coordinator alone owns claim/completion state.
        try:
            return self._run(release_id)
        except TicketSuperseded as exc:
            self.fence()
            with self.service.store.transaction() as tx:
                release = tx.get("releases", release_id)
                require(release is not None, "Release not found")
                release.update(status="superseded_by_ticket_revision", reason=str(exc))
                tx.put("releases", release_id, release)
            return {"status": "superseded_by_ticket_revision", "reason": str(exc)}

    def _reject_remaining(self, release, completed, failed):
        if failed.get("outcome") == "observation_error":
            return {"status": "retry", "reason": "verification observation unavailable",
                    "evidence": failed["evidence"], "checks": completed}
        # INV-RELEASE-001: skipped checks are explicitly unexecuted, never synthetic passes.
        receipt = self.artifacts.put(canonical({"status": "not_run",
            "reason": "prerequisite_failed", "prerequisite_ref": failed["evidence"]}),
            "canary-skipped")
        checks = {name: completed.get(name, {"passed": False, "skipped": True,
                                             "evidence": receipt["ref"]})
                  for name in release["policy"]["checks"]}
        verified = self.releases.verify(release["id"], release["candidate"]["revision"],
                                        release["policy_hash"], checks)
        return {"status": verified["status"], "checks": checks}

    def _run(self, release_id: str) -> dict:
        with self.service.store.transaction() as tx:
            release = tx.get("releases", release_id)
            active = tx.get("deployment", "active")
            image_record = tx.get("images", release_id)
        require(release is not None, "Release not found")
        if release["status"] == "active":
            require(active and active["release_id"] == release_id, "Release is not the active deployment")
            return {"status": "active", "already_applied": True, "pointer": active}
        if release["status"] == "verified":
            require(image_record is not None, "Verified image receipt missing")
            return self._promote(release, active, image_record["image"])
        require(release["status"] == "reviewed", "Release not reviewed")
        candidate = release["candidate"]
        with self.service.store.transaction() as tx:
            ticket_binding(tx, candidate)
        current_main = self.git._git("rev-parse", "HEAD")
        if current_main != candidate["base"]:
            request = Workflow(self.service.store, self.service.org).request_rebase(candidate["task_id"], current_main)
            return {"status": "rebasing", "task_id": request["message_id"]}
        inspected = self.git.inspect(candidate["revision"], candidate["base"])
        require(inspected["tree"] == candidate["tree"], "Candidate tree mismatch")
        incumbent = self.git.review_workspace(candidate["base"], "evaluator-" + release_id[:16])
        path = self.git.review_workspace(candidate["revision"], "canary-" + release_id[:16])
        # Fresh candidate venv; test definitions are taken from the incumbent commit.
        install = self._check(["uv", "sync", "--frozen"], path)
        if not install["passed"]:
            return self._reject_remaining(release, {}, install)
        python = Path(path) / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        with VerificationServices(runtime_dir() / "verification", self.artifacts) as endpoints:
            test_env = verification_environment(endpoints)
            incumbent_env = {**test_env, "PYTHONPATH": str(Path(incumbent) / "tests")}
            tests = self._check([str(python), "-m", "pytest", str(Path(incumbent) / "tests"),
                "-c", str(Path(incumbent) / "pyproject.toml"), "--import-mode=importlib", "-q"], path, env=incumbent_env)
            if not tests["passed"]:
                return self._reject_remaining(release, {"tests": tests}, tests)
            candidate_tests = self._check([str(python), "-m", "pytest", "-q"], path, env=test_env)
            if not candidate_tests["passed"]:
                return self._reject_remaining(release, {"tests": candidate_tests}, candidate_tests)
            tests = {"passed": True, "evidence": self.artifacts.put(
                canonical({"incumbent": tests, "candidate": candidate_tests}), "test-suites:" + release_id)["ref"]}
        image = "zeus:candidate-" + candidate["revision"][:16]
        build = self._check(["docker", "build", "-t", image, path], timeout=600)
        if not build["passed"]:
            return self._reject_remaining(release, {"tests": tests}, build)
        else:
            inspected_image = run_process(["docker", "image", "inspect", image, "--format", "{{.Id}}"], timeout=30)
            require(inspected_image.returncode == 0, "Candidate image missing")
            image = inspected_image.stdout.strip()
            start = self._check(["docker", "run", "--rm", "--memory", "512m", "--cpus", "1",
                                 "--entrypoint", "codex", image, "--version"])
            if not start["passed"]:
                return self._reject_remaining(release, {"tests": tests, "cli_start": start}, start)
            task = self.file_canary(image)
            checks = {"tests": tests, "cli_start": start, "cli_file_task": task}
            if not task["passed"]:
                return self._reject_remaining(release, checks, task)
            with self.service.store.transaction() as tx:
                tx.put("images", release_id, {"id": release_id, "image": image, "revision": candidate["revision"]})
        if candidate.get("hook_id"):
            hook_checks = NativeHooks(self.service, self.git, self.artifacts).canary(candidate["hook_id"])
            checks.update({"hook_" + name: check for name, check in hook_checks.items()})
            hook = self.service.get_hook(candidate["hook_id"])
            self.service.record_canary(hook["id"], candidate["revision"], digest(hook["spec"]),
                                       {**{name: check["passed"] for name, check in hook_checks.items()},
                                        "cli_start": checks["cli_file_task"]["passed"]})
        verified = self.releases.verify(release_id, candidate["revision"], release["policy_hash"], checks)
        if verified["status"] != "verified":
            return {"status": verified["status"], "checks": checks}
        return self._promote(verified, active, image)

    def _promote(self, release, active, image):
        release_id, candidate, checks = release["id"], release["candidate"], release["checks"]
        self.fence()
        with self.service.store.transaction() as tx:
            ticket_binding(tx, candidate)
            intent = tx.get("promotion_intents", release_id)
        current_main = self.git._git("rev-parse", "HEAD")
        if not intent and current_main != candidate["base"]:
            request = Workflow(self.service.store, self.service.org).request_rebase(
                candidate["task_id"], current_main)
            return {"status": "rebasing", "task_id": request["message_id"]}
        if intent:
            require(intent["status"] != "abandoned", "Promotion abandoned")
            require(intent["candidate_hash"] == digest(candidate) and intent["image"] == image
                    and intent["remote"] == self.git.remote,
                    "Promotion intent identity changed")
        else:
            intent = {"id": release_id, "candidate_hash": digest(candidate), "image": image,
                      "candidate": candidate, "expected_active": (active or {}).get("release_id"),
                      "status": "prepared", "remote": self.git.remote, "at": utcnow()}
            with self.service.store.transaction() as tx:
                ticket_binding(tx, candidate)
                require(tx.get("promotion_intents", release_id) is None, "Concurrent promotion intent")
                require((tx.get("deployment", "active") or {}).get("release_id") == intent["expected_active"],
                        "Active deployment changed")
                tx.put("promotion_intents", release_id, intent)
        with self.service.store.transaction() as tx:
            require((tx.get("deployment", "active") or {}).get("release_id") == intent["expected_active"],
                    "Active deployment changed")
        # INV-RECOVERY-001: an interrupted external operation needs positive evidence.
        # A local journal cannot prove an unrecorded GitHub merge or implement remote CAS.
        merged = intent.get("merge")
        if intent["remote"] and intent.get("external_started") and not merged:
            return {"status": "blocked_remote", "reason": "Remote side effect needs independent reconciliation"}
        if merged:
            expected_head = merged.get("merged_revision", candidate["revision"])
        else:
            expected_head = candidate["revision"] if not intent["remote"] else None
        if current_main == expected_head:
            require(not self.git._git("status", "--porcelain"), "Main worktree is dirty")
            require(self.git._git("rev-parse", "HEAD^{tree}") == candidate["tree"], "Recovered merge tree mismatch")
            merged = merged or {"merged": True, "revision": candidate["revision"], "transport": "local",
                                "recovered": True}
        elif current_main != candidate["base"] or merged:
            return {"status": "blocked", "reason": "Git position differs from durable promotion intent"}
        else:
            if intent["remote"]:
                self.fence()
                intent["external_started"] = True
                with self.service.store.transaction() as tx:
                    tx.put("promotion_intents", release_id, intent)
                self.git.publish(candidate, "Harness improvement " + candidate["revision"][:12],
                    "Implements a reviewed harness improvement.\n\n"
                    "Independent reviews and incumbent-policy checks:\n"
                    + canonical({"reviews": release["reviews"], "checks": checks}))
            if not self.auto_merge:
                return {"status": "verified", "image": image, "checks": checks}
            self.fence()
            with self.service.store.transaction() as tx:
                ticket_binding(tx, candidate)
            merged = self.git.merge(candidate)
            self.fence()
            intent.update(status="merged", merge=merged)
            with self.service.store.transaction() as tx:
                tx.put("promotion_intents", release_id, intent)
        self.fence()
        if not self.auto_merge:
            return {"status": "verified", "image": image, "checks": checks}
        with self.service.store.transaction() as tx:
            pointer = self.releases.promote(release_id, intent["expected_active"], transaction=tx)
            if candidate.get("hook_id"):
                self.service.activate(candidate["hook_id"], transaction=tx)
            tx.put("promotion_intents", release_id, {**intent, "status": "completed", "merge": merged})
        return {"status": "active", "pointer": pointer, "image": image, "merge": merged}

    def abandon(self, release_id, reason):
        """Cancel only a provably unmerged, inactive promotion; never guess remote recovery."""
        require(isinstance(reason, str) and reason.strip(), "Abandon reason required")
        with self.service.store.transaction() as tx:
            intent = tx.get("promotion_intents", release_id)
            require(intent and intent["status"] == "prepared", "No prepared promotion to abandon")
            lock = tx.get("deployment_locks", "controller") or {}
            require(not lock.get("lease_until") or datetime.fromisoformat(lock["lease_until"])
                    <= datetime.now(timezone.utc), "Release controller still running")
            require(not intent.get("external_started") and not intent.get("merge"),
                    "External merge uncertain; independently reconcile GitHub before recovery")
            require(not self.git.is_ancestor(intent["candidate"]["revision"], "HEAD"),
                    "Candidate already in main; resume release recovery instead of abandoning")
            release = tx.get("releases", release_id)
            require(release is not None, "Release not found")
            # This operation changes only ledger state; it never mutates the Git worktree.
            tx.put("promotion_intents", release_id, {**intent, "status": "abandoned", "reason": reason})
            tx.put("releases", release_id, {**release, "status": "cancelled", "reason": reason})
            queue = tx.get("release_queue", release_id)
            if queue:
                tx.put("release_queue", release_id, {**queue, "status": "cancelled", "reason": reason})
            return {"status": "abandoned", "release_id": release_id}

    def file_canary(self, image: str) -> dict:
        require(self.auth.is_file(), "Codex runtime authentication missing")
        with tempfile.TemporaryDirectory(prefix="harness-container-canary-") as directory:
            root = Path(directory)
            token = "HARNESS_CANARY_" + os.urandom(8).hex()
            (root / "input.txt").write_text(token, encoding="utf-8")
            schema = {"type": "object", "additionalProperties": False,
                      "properties": {"value": {"type": "string"}}, "required": ["value"]}
            (root / "schema.json").write_text(canonical(schema), encoding="utf-8")
            name = "harness-canary-" + os.urandom(6).hex()
            command = ["docker", "run", "--rm", "--name", name, "--memory", "768m", "--cpus", "1",
                       "--mount", f"type=bind,source={root},target=/canary",
                       "--mount", f"type=bind,source={self.auth},target=/root/.codex/auth.json,readonly",
                       "--entrypoint", "codex", image, "exec", "--ephemeral", "--skip-git-repo-check",
                       "--sandbox", "danger-full-access", "-c", 'approval_policy="never"',
                       "--output-schema", "/canary/schema.json", "--output-last-message", "/canary/result.json",
                       "-C", "/canary", "Read input.txt and write its exact contents to output.txt. "
                       "Return the input contents in value. Do not use network."]
            try:
                check = self._check(command, timeout=180)
                try:
                    answer = json.loads((root / "result.json").read_text("utf-8"))
                    valid = answer["value"] == token and (root / "output.txt").read_text("utf-8") == token
                except (OSError, ValueError, KeyError):
                    valid = False
                check["passed"] = check["passed"] and valid
                return check
            finally:
                # Docker client timeout alone does not terminate the daemon-owned container.
                run_process(["docker", "rm", "-f", name], timeout=30)

    def _probe_status(self, active, check, component):
        # INV-RECOVERY-001: missing observations cannot certify a bad deployment.
        key = active["release_id"] + ":" + component
        unknown = check.get("outcome") == "observation_error"
        with self.service.store.transaction() as tx:
            previous = tx.get("health_probes", key) or {}
            failures = (0 if check["passed"] else previous.get("failures", 0)
                        if unknown else previous.get("failures", 0) + 1)
            tx.put("health_probes", key, {"id": key, "failures": failures, "at": utcnow(),
                                         "check": check})
        if check["passed"]:
            return None
        result = {"status": "unknown" if unknown else "unhealthy", "checked_at": utcnow(),
                  "component": component, "failures": failures, "check": check}
        if not unknown and failures >= POLICY.health_failure_threshold and active.get("previous"):
            previous = self.releases.rollback(active["release_id"], "Repeated CLI health check failure")
            result.update(status="rolled_back", active=previous)
        return result

    def monitor(self) -> dict:
        with self.service.store.transaction() as tx:
            active = tx.get("deployment", "active")
            image = tx.get("images", active["release_id"]) if active else None
        if not image:
            return {"status": "unknown" if active else "no_deployment", "checked_at": utcnow()}
        check = self._check(["docker", "run", "--rm", "--memory", "512m", "--entrypoint", "codex",
                             image["image"], "--version"], timeout=45)
        if result := self._probe_status(active, check, "image"):
            return result
        try:
            running = run_process(["docker", "compose", "ps", "--format", "json"],
                                  cwd=str(self.git.repository), timeout=30, env=compose_environment())
            if running.returncode:
                return {"status": "unknown", "checked_at": utcnow(), "reason": "container listing unavailable"}
            rows = [json.loads(line) for line in running.stdout.splitlines() if line.startswith("{")]
            actual = run_process(["docker", "image", "inspect", image["image"], "--format", "{{.Id}}"], timeout=20)
            if actual.returncode or not actual.stdout.strip():
                return {"status": "unknown", "checked_at": utcnow(), "reason": "expected image unavailable"}
            drift = []
            for container in rows:
                if container.get("Service") not in {"conductor", "research-lead", "improvement-lead",
                        "implementation-worker", "github-worker", "geeknews-worker"}:
                    continue
                inspection = run_process(["docker", "inspect", container["ID"], "--format", "{{.Image}}"], timeout=20)
                if inspection.returncode or not inspection.stdout.strip():
                    return {"status": "unknown", "checked_at": utcnow(), "reason": "container inspection unavailable"}
                if inspection.stdout.strip() != actual.stdout.strip():
                    drift.append({"service": container["Service"], "expected": actual.stdout.strip(),
                                  "observed": inspection.stdout.strip()})
                    continue
                check = self._check(["docker", "exec", container["ID"], "codex", "--version"], timeout=30)
                if result := self._probe_status(active, check, container["Service"]):
                    return result
            # Idle agents intentionally exit. Absence alone is not image drift.
            return {"status": "degraded" if drift else "healthy", "checked_at": utcnow(),
                    "check": check, "image_drift": drift}
        except (OSError, subprocess.TimeoutExpired, ValueError, KeyError):
            return {"status": "unknown", "checked_at": utcnow(), "reason": "container observation unavailable"}
