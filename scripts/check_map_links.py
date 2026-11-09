#!/usr/bin/env python3
"""Check that the paths and test names in a control map exist.

Usage: check_map_links.py [--paths-only] <file.md> [<file.md> ...]
Run from anywhere. Paths are relative to the repo root.

A backticked word counts as a path when it holds a slash or ends in a known file extension.
A backticked word that starts with `test_` counts as a test name and must appear as
`def test_...` under tests/. With --paths-only the test names are not checked.
Exit 1 when anything is missing.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXTENSIONS = (".md", ".py", ".yml", ".yaml", ".json", ".toml", ".bicep", ".sql", ".sh", ".txt", ".lock")
TOKEN = re.compile(r"`([^`\n]+)`")


def _is_path(token: str) -> bool:
    if " " in token or token.startswith("-") or token.startswith("$"):
        return False
    if token.startswith("test_") and "/" not in token and "::" not in token:
        return False
    return "/" in token or token.endswith(EXTENSIONS)


def _is_test_name(token: str) -> bool:
    return bool(re.fullmatch(r"test_\w+", token))


def _test_names() -> set[str]:
    names: set[str] = set()
    for path in (REPO / "tests").glob("*.py"):
        names.update(re.findall(r"def (test_\w+)", path.read_text(encoding="utf-8")))
    return names


def check(files: list[Path], paths_only: bool) -> list[str]:
    errors: list[str] = []
    tests = None if paths_only else _test_names()
    for file in files:
        for lineno, line in enumerate(file.read_text(encoding="utf-8").splitlines(), 1):
            if not line.startswith("|"):
                continue
            for token in TOKEN.findall(line):
                if _is_path(token):
                    target = token.split("::")[0]
                    if "*" in target or "<" in target:
                        continue
                    if not (REPO / target).exists():
                        errors.append(f"{file.name}:{lineno}: missing path {token}")
                elif tests is not None and _is_test_name(token) and token not in tests:
                    errors.append(f"{file.name}:{lineno}: missing test {token}")
    return errors


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if a != "--paths-only"]
    if not args:
        print(__doc__)
        return 2
    files = [Path(a) for a in args]
    errors = check(files, "--paths-only" in argv)
    for e in errors:
        print(f"FAIL: {e}")
    if not errors:
        print(f"links ok in {len(files)} file(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
