"""k-anonymity on the quasi-identifiers of the patient dimension.

A group is the set of rows that share the same quasi-identifier values. Every group must
hold at least k rows. If a group is smaller, the code makes the values coarser, one step at
a time, for all rows. If groups are still too small after the last step, it drops those rows.

This lowers re-identification risk. It does not remove it, and it is not a compliance claim.
"""

from __future__ import annotations

import os
from collections import Counter
from collections.abc import Iterable, Mapping
from typing import Any

K_ENV = "FHIR_K_ANON"
DEFAULT_K = 5
QUASI_IDENTIFIERS = ("birth_year", "state", "gender")
LADDER = ("birth_decade", "region", "suppress")

# US Census regions. A state that is not listed becomes "Other".
STATE_REGION: dict[str, str] = {
    **dict.fromkeys(["CT", "ME", "MA", "NH", "RI", "VT", "NJ", "NY", "PA"], "Northeast"),
    **dict.fromkeys(
        ["IL", "IN", "MI", "OH", "WI", "IA", "KS", "MN", "MO", "NE", "ND", "SD"], "Midwest"
    ),
    **dict.fromkeys(
        ["DE", "DC", "FL", "GA", "MD", "NC", "SC", "VA", "WV", "AL", "KY", "MS", "TN",
         "AR", "LA", "OK", "TX"],
        "South",
    ),
    **dict.fromkeys(
        ["AZ", "CO", "ID", "MT", "NV", "NM", "UT", "WY", "AK", "CA", "HI", "OR", "WA"], "West"
    ),
}

Row = dict[str, Any]


def get_k() -> int:
    k = int(os.environ.get(K_ENV, DEFAULT_K))
    if k < 1:
        raise ValueError(f"{K_ENV} must be at least 1")
    return k


def group_sizes(
    rows: Iterable[Mapping[str, Any]], qi: tuple[str, ...] = QUASI_IDENTIFIERS
) -> Counter[tuple[Any, ...]]:
    """Count rows for each combination of quasi-identifier values."""
    return Counter(tuple(r.get(c) for c in qi) for r in rows)


def _decade(value: Any) -> Any:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return f"{int(value) // 10 * 10}s"
    return value


def _region(value: Any) -> Any:
    if value is None:
        return None
    return STATE_REGION.get(str(value), "Other")


def _generalize(rows: list[Row], step: str, qi: tuple[str, ...]) -> list[Row]:
    out = []
    for r in rows:
        n = dict(r)
        if step == "birth_decade" and "birth_year" in qi:
            n["birth_year"] = _decade(r.get("birth_year"))
        elif step == "region" and "state" in qi:
            n["state"] = _region(r.get("state"))
        out.append(n)
    return out


def enforce_k(
    rows: Iterable[Mapping[str, Any]],
    k: int | None = None,
    qi: tuple[str, ...] = QUASI_IDENTIFIERS,
    ladder: tuple[str, ...] = LADDER,
) -> tuple[list[Row], dict[str, Any]]:
    """Return rows where every quasi-identifier group has at least k rows, plus a report.

    Steps run in the order of `ladder`: `birth_decade` (birth year becomes a decade string such
    as "1960s"), `region` (state becomes a census region), `suppress` (drop the rows that are
    still in a group under k). Each generalization step applies to all rows, so a column keeps
    one type. The next step runs only when a group is still under k.
    """
    k = get_k() if k is None else k
    current: list[Row] = [dict(r) for r in rows]
    applied: list[str] = []
    suppressed = 0
    for step in ladder:
        sizes = group_sizes(current, qi)
        if not sizes or min(sizes.values()) >= k:
            break
        if step == "suppress":
            kept = [r for r in current if sizes[tuple(r.get(c) for c in qi)] >= k]
            suppressed = len(current) - len(kept)
            current = kept
            applied.append(step)
        else:
            current = _generalize(current, step, qi)
            applied.append(step)
    final = group_sizes(current, qi)
    report = {
        "k": k,
        "quasi_identifiers": list(qi),
        "steps_applied": applied,
        "rows_in": len(current) + suppressed,
        "rows_out": len(current),
        "suppressed_rows": suppressed,
        "min_group_size": min(final.values()) if final else 0,
        "groups": len(final),
    }
    return current, report
