#!/usr/bin/env python3
"""Check the list of accepted security findings. Standard library only.

Usage: check_security_exceptions.py <exceptions.json>
Exit 1 when an item lacks a field or has an expiry date in the past.
"""

from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

FIELDS = ("id", "tool", "reason", "owner", "expires", "review_note")
MAX_DAYS = 90


def check(items: object, today: date | None = None) -> list[str]:
    today = today or date.today()
    if not isinstance(items, list):
        return ["file must hold a JSON list"]
    errors: list[str] = []
    for n, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f"item {n}: must be an object")
            continue
        for field in FIELDS:
            if not item.get(field):
                errors.append(f"item {n}: missing field '{field}'")
        raw = item.get("expires")
        if raw:
            try:
                expires = date.fromisoformat(str(raw))
            except ValueError:
                errors.append(f"item {n}: 'expires' is not an ISO date")
                continue
            if expires < today:
                errors.append(f"item {n}: expired on {expires}")
            elif expires > today + timedelta(days=MAX_DAYS):
                errors.append(f"item {n}: expires more than {MAX_DAYS} days ahead")
    return errors


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    errors = check(json.loads(Path(argv[1]).read_text(encoding="utf-8")))
    for e in errors:
        print(f"FAIL: {e}")
    if not errors:
        print("exceptions ok")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
