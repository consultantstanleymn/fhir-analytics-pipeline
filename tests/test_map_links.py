from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location("check_map_links", REPO / "scripts" / "check_map_links.py")
assert _SPEC and _SPEC.loader
mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(mod)


def test_repo_map_has_no_broken_links() -> None:
    assert mod.check([REPO / "docs" / "engagement" / "HIPAA-STYLE-MAP.md"], paths_only=False) == []


def test_missing_path_and_test_are_found(tmp_path: Path) -> None:
    doc = tmp_path / "m.md"
    doc.write_text("| a | `src/nope.py` | `test_nothing_like_this` | `README.md` |\n")
    errors = mod.check([doc], paths_only=False)
    assert len(errors) == 2
    assert any("src/nope.py" in e for e in errors)
    assert any("test_nothing_like_this" in e for e in errors)


def test_paths_only_skips_test_names(tmp_path: Path) -> None:
    doc = tmp_path / "m.md"
    doc.write_text("| `test_nothing_like_this` | `README.md` |\n")
    assert mod.check([doc], paths_only=True) == []
