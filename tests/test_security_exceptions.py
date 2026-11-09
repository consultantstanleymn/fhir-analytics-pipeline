from __future__ import annotations

import importlib.util
from datetime import date, timedelta
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "check_security_exceptions",
    Path(__file__).resolve().parents[1] / "scripts" / "check_security_exceptions.py",
)
assert _SPEC and _SPEC.loader
mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(mod)


def _item(**kw: str) -> dict[str, str]:
    base = {
        "id": "X-1",
        "tool": "bandit",
        "reason": "test value",
        "owner": "Stanley Sujith Nelavala",
        "expires": (date.today() + timedelta(days=30)).isoformat(),
        "review_note": "reviewed",
    }
    base.update(kw)
    return base


def test_empty_list_is_good() -> None:
    assert mod.check([]) == []


def test_good_item_passes() -> None:
    assert mod.check([_item()]) == []


def test_expired_item_fails() -> None:
    errors = mod.check([_item(expires=(date.today() - timedelta(days=1)).isoformat())])
    assert any("expired" in e for e in errors)


def test_missing_field_fails() -> None:
    item = _item()
    del item["owner"]
    assert any("owner" in e for e in mod.check([item]))


def test_far_expiry_fails() -> None:
    far = (date.today() + timedelta(days=200)).isoformat()
    assert mod.check([_item(expires=far)])


def test_repo_exceptions_file_is_valid() -> None:
    import json

    path = Path(__file__).resolve().parents[1] / "security" / "exceptions.json"
    assert mod.check(json.loads(path.read_text())) == []
