"""Alias table: a CSV with columns ``variant,canonical`` that maps spellings to one name.

Typical use is a Korean/English pair that no rule can derive (``오픈AI`` -> ``OpenAI``).
Lines starting with ``#`` and blank lines are ignored; a header row is optional.
"""

from __future__ import annotations

import csv
from pathlib import Path

from .errors import UsageError
from .normalize import compact_key


def load_aliases(path: str | Path | None) -> dict[str, str]:
    """Read an alias CSV into ``{variant_key: canonical_key}`` (keys are NFKC/casefold/compact).

    Raises:
        UsageError: file missing, a row without two columns, an alias that points to itself,
            or a chain/cycle (a canonical name that is itself a variant).
    """
    if path is None:
        return {}
    p = Path(path)
    if not p.is_file():
        raise UsageError("err.aliases_missing", path=str(p))
    mapping: dict[str, str] = {}
    try:
        with p.open(encoding="utf-8-sig", newline="") as fh:
            rows = [r for r in csv.reader(fh) if r and not r[0].lstrip().startswith("#")]
    except UnicodeDecodeError as exc:
        raise UsageError("err.not_utf8", path=str(p)) from exc
    except OSError as exc:
        raise UsageError("err.aliases_unreadable", path=str(p), detail=exc.strerror or str(exc)) from exc
    if rows and [c.strip().lower() for c in rows[0][:2]] == ["variant", "canonical"]:
        rows = rows[1:]
    for lineno, row in enumerate(rows, start=1):
        if len(row) < 2 or not row[0].strip() or not row[1].strip():
            raise UsageError("err.aliases_row", path=str(p), row=lineno)
        variant, canonical = compact_key(row[0]), compact_key(row[1])
        if not variant or not canonical:
            raise UsageError("err.aliases_row", path=str(p), row=lineno)
        if variant == canonical:
            raise UsageError("err.aliases_self", path=str(p), name=row[0].strip())
        if mapping.get(variant, canonical) != canonical:
            raise UsageError("err.aliases_conflict", path=str(p), name=row[0].strip())
        mapping[variant] = canonical
    for variant, canonical in mapping.items():
        if canonical in mapping:
            raise UsageError("err.aliases_chain", path=str(p), name=canonical)
    return mapping
