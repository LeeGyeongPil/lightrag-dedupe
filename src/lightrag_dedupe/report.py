"""Human-readable terminal output for ``scan`` and ``explain`` (all text comes from the message table)."""

from __future__ import annotations

from .graphml import Graph
from .i18n import Translator
from .normalize import NormResult
from .plan import Item, Plan


def _item_line(item: Item, tr: Translator) -> str:
    mark = tr("scan.mark_apply") if item.apply else tr("scan.mark_skip")
    others = []
    for m in item.members:
        if m.name == item.target:
            continue
        rules = f" [{'; '.join(m.rules)}]" if m.rules else ""
        others.append(f"'{m.name}'{rules}")
    flags = ""
    if item.flags:
        flags = "  (" + ", ".join(tr(f"flag.{f}") for f in item.flags) + ")"
    score = f"  J={item.jaccard}" if item.jaccard is not None else ""
    return f"  {item.id} {mark:<5} '{item.target}' <- {', '.join(others)}{flags}{score}"


def scan_summary(plan: Plan, graph: Graph, tr: Translator) -> list[str]:
    """Lines printed after ``scan``; includes the ``groups:`` and ``review:`` summary lines."""
    conflicts = sum(1 for g in plan.groups if "type_conflict" in g.flags)
    auto = sum(1 for g in plan.groups if g.apply)
    lines = [
        tr("scan.nodes", nodes=len(graph.nodes), edges=len(graph.edges)),
        tr("scan.groups", total=len(plan.groups), auto=auto, conflicts=conflicts),
        tr("scan.review", count=len(plan.review)),
    ]
    if plan.review_truncated:
        lines.append(tr("scan.review_truncated", count=plan.review_truncated))
    for item in plan.groups:
        lines.append(_item_line(item, tr))
    for item in plan.review:
        lines.append(_item_line(item, tr))
    return lines


def explain_lines(name: str, entity_type: str, norm: NormResult, same_key: list[str], tr: Translator) -> list[str]:
    """Lines printed by ``explain``: the rule chain, the key and the nodes that share it."""
    lines = [tr("explain.name", name=name, entity_type=entity_type or "-")]
    if not norm.steps:
        lines.append(tr("explain.no_steps"))
    for n, step in enumerate(norm.steps, start=1):
        base = "guard_too_short" if step.rule.startswith("guard:") else step.rule.split(":")[0]
        what = tr(f"rule.{base}")
        extra = ""
        if step.rule.startswith("ko_particle") and step.detail:
            extra = " " + tr(f"explain.particle_{step.detail}")
        lines.append(tr("explain.step", n=n, rule=step.rule, text=step.text, what=what) + extra)
    lines.append(tr("explain.key", key=norm.key))
    others = [s for s in same_key if s != name]
    if others:
        lines.append(tr("explain.same_key"))
        lines.extend(f"  - {s}" for s in others)
    else:
        lines.append(tr("explain.alone"))
    return lines
