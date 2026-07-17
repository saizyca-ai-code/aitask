"""Guard that AICONTEXT.md is shipped as an importable package resource.

AICONTEXT.md is a RUNTIME resource, not just a doc — aitask_get_conventions
reads it and hands it to MCP clients. It previously lived at the repo root,
which worked only because every install was `pip install -e`; a real wheel
would not have carried it and the tool would have returned "not found".

These tests pin both halves of the fix: the file lives inside the package
dir, and pyproject declares it as package-data (setuptools only collects
package-data from under the package dir, so both are needed for a wheel to
include it).

Deliberately does not import aitask.mcp — that needs the optional `mcp`
extra, which CI does not install.
"""
from __future__ import annotations

from pathlib import Path

import aitask

_PKG_DIR = Path(aitask.__file__).resolve().parent
_REPO_ROOT = Path(__file__).resolve().parent.parent


def test_aicontext_lives_inside_the_package():
    p = _PKG_DIR / "AICONTEXT.md"
    assert p.is_file(), (
        f"AICONTEXT.md must sit next to the aitask modules ({_PKG_DIR}) so "
        "wheel installs ship it; moving it back to the repo root silently "
        "breaks aitask_get_conventions for non-editable installs."
    )


def test_aicontext_is_the_conventions_doc():
    text = (_PKG_DIR / "AICONTEXT.md").read_text(encoding="utf-8")
    assert "AI 開發夥伴 conventions" in text
    assert "否決方案" in text


def test_pyproject_declares_aicontext_as_package_data():
    text = (_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "[tool.setuptools.package-data]" in text
    assert "AICONTEXT.md" in text
