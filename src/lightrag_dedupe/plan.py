"""Merge plan data model and its JSON / CSV files.

``plan.json`` carries everything (evidence, flags, graph hash) and is byte-for-byte reproducible:
no timestamps, no absolute paths. ``plan.csv`` has one row per member so a spreadsheet can be used
for review; its column names are always English.

Human edits that are honored when applying:

* ``apply`` - ``true`` / ``false`` per group (review rows start as ``false``).
* ``target`` - the name that survives. If it is not one of the members it is created.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import UsageError
from .rules import RULE_CODES

FORMAT = "lightrag-dedupe/plan@1"
CSV_COLUMNS = ("group_id", "apply", "target", "member", "role", "entity_type", "degree", "chunks", "rules")
_TRUE = {"true", "yes", "y", "1"}
_FALSE = {"false", "no", "n", "0"}


@dataclass(frozen=True)
class Member:
    name: str
    entity_type: str
    degree: int
    chunks: int
    rules: tuple[str, ...]


@dataclass
class Item:
    """A merge group (``G001``) or a near-pair for review (``R001``)."""

    id: str
    apply: bool
    target: str
    sources: list[str]
    members: list[Member]
    flags: list[str] = field(default_factory=list)
    jaccard: float | None = None  # only for review items


@dataclass
class Plan:
    graph_sha256: str
    node_count: int
    options: dict[str, Any]
    groups: list[Item] = field(default_factory=list)
    review: list[Item] = field(default_factory=list)
    review_truncated: int = 0


@dataclass(frozen=True)
class Merge:
    """What ``apply`` needs: merge ``sources`` into ``target`` (names exactly as stored)."""

    id: str
    target: str
    sources: tuple[str, ...]


@dataclass(frozen=True)
class LoadedPlan:
    merges: list[Merge]  # only items with apply=true, validated
    graph_sha256: str | None  # None for CSV (the CSV does not carry it)
    skipped: int  # items with apply=false


def _item_dict(item: Item) -> dict[str, Any]:
    d: dict[str, Any] = {
        "id": item.id,
        "apply": item.apply,
        "target": item.target,
        "sources": list(item.sources),
        "members": [
            {
                "name": m.name,
                "entity_type": m.entity_type,
                "degree": m.degree,
                "chunks": m.chunks,
                "rules": list(m.rules),
            }
            for m in item.members
        ],
        "flags": list(item.flags),
    }
    if item.jaccard is not None:
        d["jaccard"] = item.jaccard
    return d


def plan_to_dict(plan: Plan) -> dict[str, Any]:
    return {
        "format": FORMAT,
        "graph_sha256": plan.graph_sha256,
        "node_count": plan.node_count,
        "options": plan.options,
        "rule_codes": list(RULE_CODES),
        "groups": [_item_dict(i) for i in plan.groups],
        "review": [_item_dict(i) for i in plan.review],
        "review_truncated": plan.review_truncated,
    }


def plan_json_text(plan: Plan) -> str:
    return json.dumps(plan_to_dict(plan), ensure_ascii=False, indent=2) + "\n"


def _write_text(path: str | Path, text: str, encoding: str) -> None:
    try:
        with open(path, "w", encoding=encoding, newline="") as fh:
            fh.write(text)
    except OSError as exc:
        raise UsageError("err.write_failed", path=str(path), detail=exc.strerror or str(exc)) from exc


def write_plan_json(plan: Plan, path: str | Path) -> None:
    _write_text(path, plan_json_text(plan), "utf-8")


def plan_csv_text(plan: Plan) -> str:
    import io

    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)
    for item in [*plan.groups, *plan.review]:
        for m in item.members:
            writer.writerow(
                [
                    item.id,
                    "true" if item.apply else "false",
                    item.target,
                    m.name,
                    "target" if m.name == item.target else "source",
                    m.entity_type,
                    m.degree,
                    m.chunks,
                    ";".join(m.rules),
                ]
            )
    return buf.getvalue()


def write_plan_csv(plan: Plan, path: str | Path) -> None:
    # utf-8-sig: the BOM makes Excel (also on Korean Windows) show the names correctly.
    _write_text(path, plan_csv_text(plan), "utf-8-sig")


# ----------------------------------------------------------------------------- reading


def _parse_bool(value: Any, where: str) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    raise UsageError("err.plan_apply_value", where=where, value=str(value))


def _validate(merges: list[Merge]) -> None:
    seen_sources: dict[str, str] = {}
    targets = {m.target: m.id for m in merges}
    for m in merges:
        if not m.target.strip():
            raise UsageError("err.plan_empty_target", id=m.id)
        if not m.sources:
            raise UsageError("err.plan_empty_sources", id=m.id)
        if m.target in m.sources:
            raise UsageError("err.plan_target_in_sources", id=m.id, name=m.target)
        for s in m.sources:
            if not isinstance(s, str) or not s.strip():
                raise UsageError("err.plan_empty_sources", id=m.id)
            if s in seen_sources:
                raise UsageError("err.plan_overlap", name=s, a=seen_sources[s], b=m.id)
            if s in targets and targets[s] != m.id:
                raise UsageError("err.plan_overlap", name=s, a=targets[s], b=m.id)
            seen_sources[s] = m.id


def _load_json(path: Path) -> LoadedPlan:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except UnicodeDecodeError as exc:
        raise UsageError("err.not_utf8", path=str(path)) from exc
    except (OSError, ValueError) as exc:
        raise UsageError("err.plan_invalid", path=str(path), detail=str(exc)) from exc
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        found = data.get("format") if isinstance(data, dict) else None
        raise UsageError("err.plan_format", found=str(found), expected=FORMAT)
    merges: list[Merge] = []
    skipped = 0
    items = [*(data.get("groups") or []), *(data.get("review") or [])]
    for raw in items:
        if not isinstance(raw, dict) or "id" not in raw:
            raise UsageError("err.plan_invalid", path=str(path), detail="item without id")
        where = str(raw["id"])
        if not _parse_bool(raw.get("apply", False), where):
            skipped += 1
            continue
        sources = raw.get("sources")
        if not isinstance(sources, list):
            raise UsageError("err.plan_empty_sources", id=where)
        merges.append(Merge(where, str(raw.get("target", "")), tuple(str(s) for s in sources)))
    _validate(merges)
    sha = data.get("graph_sha256")
    return LoadedPlan(merges, sha if isinstance(sha, str) else None, skipped)


def _load_csv(path: Path) -> LoadedPlan:
    try:
        with path.open(encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            fields = reader.fieldnames or []
            rows = list(reader)
    except UnicodeDecodeError as exc:
        raise UsageError("err.not_utf8", path=str(path)) from exc
    except OSError as exc:
        raise UsageError("err.plan_invalid", path=str(path), detail=str(exc)) from exc
    missing = [c for c in ("group_id", "apply", "target", "member") if c not in fields]
    if missing:
        raise UsageError("err.plan_csv_columns", missing=", ".join(missing))
    order: list[str] = []
    by_id: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        gid = (row.get("group_id") or "").strip()
        if not gid:
            continue
        if gid not in by_id:
            order.append(gid)
            by_id[gid] = []
        by_id[gid].append(row)
    merges: list[Merge] = []
    skipped = 0
    for gid in order:
        group_rows = by_id[gid]
        applies = {_parse_bool(r.get("apply", ""), gid) for r in group_rows}
        targets = {(r.get("target") or "").strip() for r in group_rows}
        if len(applies) > 1:
            raise UsageError("err.plan_csv_inconsistent", id=gid, column="apply")
        if len(targets) > 1:
            raise UsageError("err.plan_csv_inconsistent", id=gid, column="target")
        if not applies.pop():
            skipped += 1
            continue
        target = targets.pop()
        sources: list[str] = []
        for r in group_rows:
            member = r.get("member") or ""
            if member and member != target and member not in sources:
                sources.append(member)
        merges.append(Merge(gid, target, tuple(sources)))
    _validate(merges)
    return LoadedPlan(merges, None, skipped)


def load_plan(path: str | Path) -> LoadedPlan:
    """Read ``plan.json`` or ``plan.csv`` (chosen by extension) and return the groups to apply.

    Raises:
        UsageError: file missing, unknown format version, empty sources, target among sources,
            a name used by two groups, or malformed CSV.
    """
    p = Path(path)
    if not p.is_file():
        raise UsageError("err.plan_missing", path=str(p))
    if p.suffix.lower() == ".csv":
        return _load_csv(p)
    return _load_json(p)
