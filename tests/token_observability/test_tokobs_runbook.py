"""ACCEPTANCE A30 (W2b, static): the runbook's commands target only the `zeus-tokobs*` project, the tokobs directory
and the U3 secret file. It parses the fenced code blocks of `docs/observability/RUNBOOK.md`; nothing is executed."""

import re
import shlex
from pathlib import Path

RUNBOOK = Path(__file__).resolve().parents[2] / "docs" / "observability" / "RUNBOOK.md"
SECRET = "/srv/zeus/secrets/grafana-admin.pass"
RM_TARGETS = {"/srv/zeus/runtime/tokobs", SECRET}
PROJECT = re.compile(r"-p\s+zeus-tokobs(?:-conntest)?(?=\s|$)")


def code_lines() -> list[str]:
    """Commands of every fenced block: backslash continuations joined, blank lines and comments dropped."""
    text, lines = RUNBOOK.read_text(), []
    for block in re.findall(r"^[ \t]*```[a-z]*\n(.*?)^[ \t]*```", text, re.M | re.S):
        for line in re.sub(r"\\\n\s*", " ", block).splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                lines.append(line)
    return lines


def test_the_runbook_has_commands_and_every_required_section():
    text = RUNBOOK.read_text()
    for heading in ("Scope and authority", "Install", "Post-checks", "Access", "Update", "Rollback / isolated cleanup",
                    "What is not touched"):
        assert re.search(rf"^## {re.escape(heading)}", text, re.M), heading
    assert "U1" in text and "U3" in text
    assert len(code_lines()) >= 8


def test_a30_every_docker_compose_command_names_a_tokobs_project():
    seen = 0
    for line in code_lines():
        for part in re.split(r"(?=docker\s+compose\b)", line)[1:]:
            seen += 1
            assert PROJECT.search(part), line
    assert seen >= 5


def test_a30_no_docker_prune_or_removal_outside_the_project():
    for line in code_lines():
        assert not re.search(r"\bdocker\s+(?:system|volume|network|image|container|builder)\s+prune\b", line), line
        assert not re.search(r"\bdocker\s+(?:(?:container|volume|network|image)\s+)?(?:rm|rmi)\b", line), line
        assert not re.search(r"\bdocker\s+(?:kill|stop|restart)\b", line), line


def test_a30_cleanup_is_exactly_down_then_the_two_rm_targets():
    lines = code_lines()
    start = lines.index("docker compose -p zeus-tokobs -f deploy/observability/compose.yaml down -v")
    assert lines[start + 1:start + 3] == ["rm -rf -- /srv/zeus/runtime/tokobs", f"rm -- {SECRET}"]
    assert sum(" down" in line for line in lines) == 1


def test_a30_every_rm_targets_only_the_tokobs_dir_or_the_secret_file():
    seen = []
    for line in code_lines():
        for match in re.finditer(r"(?:^|[;&|(]\s*)rm\s+([^;&|)]*)", line):
            targets = [t for t in shlex.split(match.group(1)) if not t.startswith("-")]
            assert targets and set(targets) <= RM_TARGETS, line
            seen += targets
    assert sorted(seen) == sorted(RM_TARGETS)


def test_a30_no_host_unit_or_firewall_changes():
    for line in code_lines():
        assert not re.search(r"\b(?:systemctl|ufw|iptables|ip6tables|nft|firewall-cmd)\b", line), line
        assert not re.search(r"\bsudo\s+tee\b", line), line
        assert not re.search(r"/etc/(?:systemd|ufw)|/usr/lib/systemd", line), line


def test_a30_the_secret_is_never_echoed_or_read_back():
    for line in code_lines():
        assert not re.search(r"\b(?:cat|echo|head|tail|less|more|xxd|od|base64|strings|tee|cp|mv)\b.*"
                             rf"(?:{re.escape(SECRET)}|\$pw|\$\{{pw)", line), line
        if "$pw" in line:
            # the only use of the typed value is a redirect into the secret file
            assert re.fullmatch(rf"IFS= read -rs -p '[^']*' pw && printf '%s' \"\$pw\" > {re.escape(SECRET)}; unset pw",
                                line), line
        if SECRET in line:
            assert re.match(r"(?:install -m 0600 -o 1000 -g 1000 /dev/null|IFS= read|rm --) ", line), line
    assert "set -x" not in " ".join(code_lines())


def test_a30_post_check_4_is_the_lint_deploy_pipeline_and_the_install_modes_are_the_design_ones():
    lines = code_lines()
    assert ("docker inspect $(docker compose -p zeus-tokobs -f deploy/observability/compose.yaml ps -q) | "
            "PYTHONPATH=tools/token_observability:src python3 -B -m tokobs lint-deploy --inspect-json -") in lines
    assert "install -d -o 1000 -g 1000 -m 0700 /srv/zeus/runtime/tokobs" in lines
    assert "docker compose -p zeus-tokobs -f deploy/observability/compose.yaml up -d" in lines
    assert any(line.startswith("TOKOBS_CONNTEST=1 ") and "test_tokobs_conntest.py" in line for line in lines)
