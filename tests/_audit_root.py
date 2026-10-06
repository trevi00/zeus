"""Where the R-O import audit's root is (REBUILD-DESIGN-v2 §5.2 R-O; cutover G2-W1, critique #5).

The incumbent controller runs the INCUMBENT tests against the CANDIDATE package: two checkouts, the package
installed editable from the candidate and the pytest invocation cwd the candidate. The tests' own tree (`_layout.TARGET`)
is then not the tree `codex_harness` loads from, so the audit root must be derived. It must not come from the import
system (the audit would approve whatever it audits); it comes from the installed distribution's PEP 610 record:

- an editable `zeus-harness` install whose project directory is the pytest invocation cwd (the url is the project
  directory; `<cwd>/src` is accepted too), whose `pyproject.toml` names `zeus-harness`, and which is not under a
  `reference/` path, makes `<cwd>/src` the audit root;
- anything else (wheel, third directory, no record, another project, reference tree) keeps the tests' own tree.

Pure and stdlib only; `codex_harness` is never imported here.
"""

import json
import tomllib
from importlib import metadata
from pathlib import Path
from urllib.parse import unquote, urlparse

from _layout import TARGET

DISTRIBUTION = "zeus-harness"


def _file_url_path(url: object) -> Path | None:
    if not isinstance(url, str):
        return None
    parsed = urlparse(url)
    if parsed.scheme != "file" or parsed.netloc not in ("", "localhost"):
        return None
    return Path(unquote(parsed.path))


def _project_name(pyproject_text: str | None) -> str | None:
    if not pyproject_text:
        return None
    try:
        name = tomllib.loads(pyproject_text).get("project", {}).get("name")
    except tomllib.TOMLDecodeError:
        return None
    return name.replace("_", "-").replace(".", "-").lower() if isinstance(name, str) else None


def audit_root(direct_url: dict | None, cwd: Path, pyproject_text: str | None, default: Path) -> Path:
    """The R-O audit root: `<cwd>/src` for the matching editable install, else `default`."""
    if not isinstance(direct_url, dict):
        return default
    dir_info = direct_url.get("dir_info")
    if not isinstance(dir_info, dict) or dir_info.get("editable") is not True:
        return default
    installed = _file_url_path(direct_url.get("url"))
    if installed is None:
        return default
    cwd = Path(cwd).resolve()
    installed = installed.resolve()
    if installed not in (cwd, cwd / "src"):
        return default
    if "reference" in installed.parts or "reference" in cwd.parts:
        return default
    if _project_name(pyproject_text) != DISTRIBUTION:
        return default
    return cwd / "src"


def installed_direct_url() -> dict | None:
    try:
        text = metadata.distribution(DISTRIBUTION).read_text("direct_url.json")
        record = json.loads(text) if text else None
    except (metadata.PackageNotFoundError, ValueError):
        return None
    return record if isinstance(record, dict) else None


def session_audit_root(default: Path, cwd: Path | None = None) -> Path:
    """`audit_root` over the real installed record, the invocation cwd and that directory's pyproject."""
    cwd = Path.cwd() if cwd is None else Path(cwd)
    try:
        text = (cwd / "pyproject.toml").read_text(encoding="utf-8")
    except OSError:
        text = None
    return audit_root(installed_direct_url(), cwd, text, default)


# The ONE trusted anchor for "the codex_harness this pytest process imports" (cutover G2-W1 follow-up W1a). A test locates
# the package under test from PACKAGE_SRC and never from its own checkout `_layout.TARGET`; a child-process helper uses
# `Path(codex_harness.__spec__.origin).parent`. TARGET locates only the tests' own tree (tests/, compare/, coverage/,
# docs/). In a same-checkout run (CI, TI, the candidate suite) PACKAGE_SRC == TARGET / "src", so nothing changes there.
PACKAGE_SRC = session_audit_root(TARGET / "src")
