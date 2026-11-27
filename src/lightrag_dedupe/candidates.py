"""Candidate generation: same-key groups, type conflicts, representative choice, near pairs.

Groups are built from exactly equal normalized keys, so there are no chains (A~B, B~C). Near pairs
(similar but not equal keys) are never merged automatically; they are only listed for review.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Mapping
from typing import Any

from .graphml import Graph, Node
from .normalize import NormResult, base_key, compact_key, normalize_name
from .plan import Item, Member, Plan

DEFAULT_NEAR = 0.6
DEFAULT_MAX_REVIEW = 500
MIN_NEAR_KEY_LENGTH = 4  # shorter keys have too few trigrams for a meaningful similarity


def _grams(key: str) -> frozenset[str]:
    return frozenset(key[i : i + 3] for i in range(len(key) - 2))


def _type_id(entity_type: str) -> str:
    return entity_type.strip().casefold()


def _rank(node: Node, norm: NormResult, canonical_keys: set[str]) -> tuple[Any, ...]:
    """Sort key for choosing the surviving name (smaller is better, fully deterministic)."""
    is_canonical = norm.key in canonical_keys and compact_key(node.name) == norm.key
    return (
        0 if is_canonical else 1,
        1 if norm.surface_rules else 0,
        -node.chunks,
        -node.degree,
        len(node.name),
        node.name,
    )


def _member(node: Node, norm: NormResult) -> Member:
    return Member(node.name, node.entity_type, node.degree, node.chunks, norm.rules)


def _near_pairs(reps: list[tuple[str, Node]], threshold: float) -> list[tuple[float, int, int]]:
    """Exact Jaccard >= threshold pairs over character trigrams, found with a prefix-filter index.

    ``reps`` holds ``(key, node)`` with distinct keys. Returns ``(jaccard, i, j)`` index pairs.
    Only the rarest trigrams of each key are indexed, so common trigrams do not blow up the
    candidate set (this keeps 20,000 nodes fast); every candidate is then verified exactly.
    """
    grams = [_grams(key) for key, _ in reps]
    freq: Counter[str] = Counter()
    for g in grams:
        freq.update(g)
    ordered = [sorted(g, key=lambda x: (freq[x], x)) for g in grams]
    by_size = sorted(range(len(reps)), key=lambda i: (len(grams[i]), i))
    index: dict[str, list[int]] = defaultdict(list)
    pairs: list[tuple[float, int, int]] = []
    eps = 1e-9
    for i in by_size:
        size = len(grams[i])
        if size == 0:
            continue
        prefix_len = size - math.ceil(threshold * size - eps) + 1
        seen: set[int] = set()
        for gram in ordered[i][:prefix_len]:
            for j in index[gram]:
                if j in seen:
                    continue
                seen.add(j)
                if len(grams[j]) < threshold * size - eps:
                    continue
                inter = len(grams[i] & grams[j])
                jac = inter / (size + len(grams[j]) - inter)
                if jac >= threshold - eps:
                    pairs.append((jac, i, j))
            index[gram].append(i)
    return pairs


def compute_norms(names: list[str], aliases: Mapping[str, str] | None = None) -> dict[str, NormResult]:
    """Normalize every node name. Particle removal needs the keys of all nodes, hence two passes."""
    alias_map = dict(aliases or {})
    known = {base_key(n) for n in names} | set(alias_map) | set(alias_map.values())
    return {n: normalize_name(n, known, alias_map) for n in names}


def scan_graph(
    graph: Graph,
    aliases: Mapping[str, str] | None = None,
    near: float = DEFAULT_NEAR,
    max_review: int = DEFAULT_MAX_REVIEW,
) -> Plan:
    """Build a merge plan from a loaded graph. Pure function: same input, same plan.

    Args:
        graph: Result of :func:`lightrag_dedupe.graphml.load_graph`.
        aliases: ``variant key -> canonical key`` from :func:`lightrag_dedupe.aliases.load_aliases`.
        near: Trigram Jaccard threshold (0 < near <= 1) for review pairs.
        max_review: Keep at most this many review pairs (highest similarity first).
    """
    alias_map = dict(aliases or {})
    names = sorted(graph.nodes)
    norms = compute_norms(names, alias_map)
    canonical_keys = set(alias_map.values())

    def rank(name: str) -> tuple[Any, ...]:
        return _rank(graph.nodes[name], norms[name], canonical_keys)

    by_key: dict[str, list[str]] = defaultdict(list)
    for n in names:
        if norms[n].key:
            by_key[norms[n].key].append(n)

    plan = Plan(
        graph_sha256=graph.sha256,
        node_count=len(graph.nodes),
        options={"near": near, "max_review": max_review, "aliases": len(alias_map)},
    )

    for key in sorted(by_key):
        members = by_key[key]
        if len(members) < 2:
            continue
        members = sorted(members, key=rank)
        target = members[0]
        types = {_type_id(graph.nodes[m].entity_type) for m in members} - {""}
        flags = ["type_conflict"] if len(types) > 1 else []
        plan.groups.append(
            Item(
                id=f"G{len(plan.groups) + 1:03d}",
                apply=not flags,
                target=target,
                sources=sorted(members[1:]),
                members=[_member(graph.nodes[m], norms[m]) for m in members],
                flags=flags,
            )
        )

    # Near pairs: inside one entity type, between different keys; never auto-applied.
    blocks: dict[str, dict[str, str]] = defaultdict(dict)  # type -> key -> best node name
    for n in names:
        key = norms[n].key
        if len(key) < MIN_NEAR_KEY_LENGTH:
            continue
        slot = blocks[_type_id(graph.nodes[n].entity_type)]
        if key not in slot or rank(n) < rank(slot[key]):
            slot[key] = n
    found: list[tuple[float, str, str, str, str]] = []
    for type_id in sorted(blocks):
        reps = sorted((key, graph.nodes[name]) for key, name in blocks[type_id].items())
        for jac, i, j in _near_pairs(reps, near):
            (ka, na), (kb, nb) = reps[i], reps[j]
            if ka > kb:
                ka, na, kb, nb = kb, nb, ka, na
            found.append((jac, ka, kb, na.name, nb.name))
    found.sort(key=lambda f: (-f[0], f[1], f[2]))
    plan.review_truncated = max(0, len(found) - max_review)
    for jac, _ka, _kb, a, b in found[:max_review]:
        a_best, b_best = sorted((a, b), key=rank)
        plan.review.append(
            Item(
                id=f"R{len(plan.review) + 1:03d}",
                apply=False,
                target=a_best,
                sources=[b_best],
                members=[_member(graph.nodes[a_best], norms[a_best]), _member(graph.nodes[b_best], norms[b_best])],
                flags=["near"],
                jaccard=round(jac, 3),
            )
        )
    return plan
