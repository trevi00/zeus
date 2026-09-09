"""Verify externally signed acceptance against an out-of-band immutable trust anchor."""
import base64
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from codex_harness.adapters.commands import run_process
from codex_harness.adapters.sdd import parse_json
from codex_harness.domain.model import canonical, digest, require
from codex_harness.domain.ticket_lifecycle import COMMIT, REF, timestamp

POLICY_PATH = ".zeus/ticket-trust.json"
PRINCIPAL = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.@-]{0,99}")


class TicketAuthority:
    def __init__(self, git, artifacts, trust_commit=None):
        self.git, self.artifacts = git, artifacts
        # Never default to HEAD or accept a packet/CLI override of the deployment anchor.
        self.trust_commit = trust_commit if trust_commit is not None else os.environ.get("ZEUS_TICKET_TRUST_COMMIT")

    def policy(self, heartbeat=None):
        def read(*args, **kwargs):
            if heartbeat:
                heartbeat()
            return self.git._git(*args, **kwargs)
        require(isinstance(self.trust_commit, str) and COMMIT.fullmatch(self.trust_commit),
                "Out-of-band ZEUS_TICKET_TRUST_COMMIT is required")
        require(read("rev-parse", "--verify", self.trust_commit + "^{commit}") == self.trust_commit,
                "Trust anchor commit unavailable")
        mode = read("ls-tree", self.trust_commit, "--", POLICY_PATH).split()
        require(mode and mode[0] == "100644", "Trust policy must be a regular Git file")
        raw = read("show", self.trust_commit + ":" + POLICY_PATH, strip=False)
        require(len(raw.encode("utf-8")) <= 65536, "Trust policy exceeds budget")
        data = parse_json(raw)
        require(isinstance(data, dict) and set(data) == {"version", "scope", "signers", "required_signers",
                "required_human_signers", "revoked", "max_evidence_age_seconds"} and type(data["version"]) is int and data["version"] == 1,
                "Invalid ticket trust policy")
        require(isinstance(data["scope"], str) and 0 < len(data["scope"]) <= 200, "Trust scope required")
        require(type(data["max_evidence_age_seconds"]) is int and 60 <= data["max_evidence_age_seconds"] <= 86400,
                "Evidence maximum age must be 60..86400 seconds")
        require(isinstance(data["signers"], list) and 0 < len(data["signers"]) <= 20, "Enrolled signers required")
        enrolled, keys = {}, set()
        for signer in data["signers"]:
            require(isinstance(signer, dict) and set(signer) == {"principal", "role", "public_key", "valid_after", "valid_before"},
                    "Invalid enrolled signer")
            principal, key = signer["principal"], signer["public_key"]
            require(isinstance(principal, str) and PRINCIPAL.fullmatch(principal) and principal not in enrolled,
                    "Invalid or duplicate signer principal")
            require(signer["role"] in {"human", "automation"}, "Invalid signer role")
            require(isinstance(key, str) and "\n" not in key and "\r" not in key, "Invalid public key")
            parts = key.split()
            require(len(parts) == 2 and parts[0] in {"ssh-ed25519", "ssh-rsa", "sk-ssh-ed25519@openssh.com"},
                    "Unsupported signer public key")
            decoded = base64.b64decode(parts[1], validate=True)
            require(decoded and decoded not in keys, "Duplicate signer public key")
            require(timestamp(signer["valid_after"]) < timestamp(signer["valid_before"]), "Invalid signer validity")
            enrolled[principal] = signer
            keys.add(decoded)
        for name in ("required_signers", "required_human_signers", "revoked"):
            value = data[name]
            require(isinstance(value, list) and all(isinstance(v, str) and v in enrolled for v in value)
                    and len(set(value)) == len(value), "Invalid " + name)
        require(data["required_signers"] and set(data["required_human_signers"]) <= set(data["required_signers"])
                and all(enrolled[p]["role"] == "human" for p in data["required_human_signers"]),
                "Required human signers must be enrolled humans and required signers")
        require(not set(data["required_signers"]) & set(data["revoked"]), "Required signer is revoked; policy is unusable")
        return {"policy_commit": self.trust_commit, "policy_hash": digest(data), "scope": data["scope"],
                "definition": data, "enrolled": enrolled}

    def verify(self, packet_ref, packet, signatures, *, at=None, heartbeat=None):
        policy = self.policy(heartbeat)
        require(all(packet[k] == policy[k] for k in ("policy_commit", "policy_hash", "scope")), "Stale signing policy")
        raw = self.artifacts.text(packet_ref, 1024 * 1024)
        require(raw == canonical(packet), "Sign exact canonical packet bytes, excluding signature envelope")
        require(isinstance(signatures, list) and 0 < len(signatures) <= 20, "Complete signature set required")
        at = at or datetime.now(timezone.utc)
        issued = timestamp(packet["issued_at"])
        seen, verified = set(), []
        for entry in signatures:
            if heartbeat:
                heartbeat()
            require(isinstance(entry, dict) and set(entry) == {"principal", "signature_ref"}, "Invalid signature envelope")
            require(isinstance(entry["signature_ref"], str) and REF.fullmatch(entry["signature_ref"]),
                    "Immutable signature reference required")
            principal = entry["principal"]
            require(isinstance(principal, str) and principal in policy["enrolled"] and principal not in seen,
                    "Unenrolled or duplicate signature principal")
            signer = policy["enrolled"][principal]
            require(principal not in policy["definition"]["revoked"], "Signer revoked")
            require(timestamp(signer["valid_after"]) <= issued <= at < timestamp(signer["valid_before"]),
                    "Signer outside validity window")
            signature = self.artifacts.text(entry["signature_ref"], 16384)
            with tempfile.TemporaryDirectory(prefix="zeus-ticket-verify-") as directory:
                root = Path(directory)
                allowed, signed = root / "allowed_signers", root / "packet.sig"
                allowed.write_text(principal + " " + signer["public_key"] + "\n", encoding="utf-8", newline="\n")
                signed.write_text(signature.replace("\r\n", "\n"), encoding="utf-8", newline="\n")
                env = {k: v for k, v in os.environ.items() if k.upper() in
                       {"PATH", "SYSTEMROOT", "WINDIR", "PROGRAMDATA", "TEMP", "TMP", "TMPDIR"}}
                env.update(HOME=directory, USERPROFILE=directory)
                try:
                    result = run_process(["ssh-keygen", "-Y", "verify", "-f", str(allowed), "-I", principal,
                        "-n", "zeus-ticket-close-v1", "-s", str(signed)], input_text=raw, env=env, timeout=30)
                except FileNotFoundError as exc:
                    raise RuntimeError("OpenSSH 8.2+ ssh-keygen with -Y verify is required") from exc
                require(result.returncode == 0, "Signature rejected; require OpenSSH 8.2+ and enrolled signing key: "
                        + result.stderr[-300:])
            seen.add(principal)
            verified.append({**entry, "role": signer["role"], "public_key_hash": digest(signer["public_key"])})
        require(set(policy["definition"]["required_signers"]) <= seen, "Incomplete required signature set")
        if heartbeat:
            heartbeat()
        self.require_merged(packet["solution_commit"])
        finished = datetime.now(timezone.utc)
        require(all(finished < timestamp(policy["enrolled"][p]["valid_before"]) for p in seen),
                "Signer expired during verification")
        return {"policy_commit": policy["policy_commit"], "policy_hash": policy["policy_hash"], "scope": policy["scope"],
                "packet_ref": packet_ref, "signatures": verified, "verified_at": finished.isoformat(),
                "required_signers": policy["definition"]["required_signers"],
                "required_human_signers": policy["definition"]["required_human_signers"],
                "attestation_scope": "configured_key_authority_only", "physical_human_presence_verified": False}

    def require_merged(self, commit):
        require(isinstance(commit, str) and COMMIT.fullmatch(commit), "Full solution commit required")
        require(self.git._git("merge-base", commit, "HEAD") == commit,
                "Solution commit must be merged into the configured repository HEAD")
