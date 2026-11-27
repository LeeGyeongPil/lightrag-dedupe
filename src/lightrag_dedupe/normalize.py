"""Name normalization: a fixed chain of rules that turns an entity name into a comparison key.

Chain (each step that changes the text leaves a rule code as evidence, in this order)::

    nfkc -> casefold -> suffix:<x> (repeated) -> ko_particle:<x> -> punct_space -> alias

Two guards keep the chain from inventing false matches:

* ``guard:too_short`` - if stripping corporate suffixes would leave fewer than
  ``MIN_KEY_LENGTH`` letters (for example the name ``Co``), the stripping is cancelled.
* ``ko_particle`` is applied only when the remaining stem is the key of another node
  (or an alias). Without that graph evidence ``마이크로`` stays ``마이크로``.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from .rules import (
    KO_CORPORATE,
    KO_PARTICLES,
    LATIN_SUFFIXES,
    MIN_KEY_LENGTH,
    SURFACE_RULE_PREFIXES,
)

_KO_PREFIX = re.compile(r"^(" + "|".join(re.escape(x) for x in KO_CORPORATE) + r")\s*")
_KO_SUFFIX = re.compile(r"\s*(" + "|".join(re.escape(x) for x in KO_CORPORATE) + r")$")
_LATIN_TAIL = re.compile(r"(?:^|[\s,])([a-z]+)\.?[\s,.]*$")


@dataclass(frozen=True)
class Step:
    """One applied rule: its code, the text after it, and an optional detail.

    For ``ko_particle`` the detail says where the evidence came from: ``"graph"`` or ``"alias"``.
    """

    rule: str
    text: str
    detail: str = ""


@dataclass(frozen=True)
class NormResult:
    """Outcome of :func:`normalize_name`."""

    key: str
    rules: tuple[str, ...]
    steps: tuple[Step, ...]

    @property
    def surface_rules(self) -> tuple[str, ...]:
        """Rules that changed how the name is written (``casefold`` alone does not count)."""
        return tuple(r for r in self.rules if r.startswith(SURFACE_RULE_PREFIXES))


def compact(text: str) -> str:
    """Keep letters and digits only (drops spaces, punctuation, symbols)."""
    return "".join(ch for ch in text if ch.isalnum())


def compact_key(text: str) -> str:
    """NFKC + casefold + letters/digits only. Used for alias table entries."""
    return compact(unicodedata.normalize("NFKC", text).casefold())


def _strip_corporate(text: str) -> tuple[str, list[str]]:
    """Repeatedly remove corporate markers from the front/back; return the rest and rule codes."""
    codes: list[str] = []
    while True:
        m = _KO_PREFIX.match(text)
        if m:
            codes.append("suffix:" + m.group(1))
            text = text[m.end() :]
            continue
        m = _KO_SUFFIX.search(text)
        if m:
            codes.append("suffix:" + m.group(1))
            text = text[: m.start()]
            continue
        m = _LATIN_TAIL.search(text)
        if m and m.group(1) in LATIN_SUFFIXES:
            codes.append("suffix:" + m.group(1))
            text = text[: m.start()].rstrip(" ,")
            continue
        return text, codes


def normalize_name(
    name: str,
    known_keys: Iterable[str] = (),
    aliases: Mapping[str, str] | None = None,
) -> NormResult:
    """Normalize ``name`` into a comparison key and the list of rules that were applied.

    Args:
        name: Entity name exactly as stored in the graph.
        known_keys: Keys of other nodes (see :func:`base_key`); a Korean particle is removed
            only if the remaining stem is one of these (or an alias key / canonical).
        aliases: Optional mapping ``variant key -> canonical key`` (both already compacted).

    Returns:
        A :class:`NormResult` with the key (possibly empty for names without letters or digits),
        the ordered rule codes and the intermediate steps.
    """
    alias_map = aliases or {}
    known = set(known_keys)
    steps: list[Step] = []

    text = name.strip()
    nfkc = unicodedata.normalize("NFKC", text)
    if nfkc != text:
        steps.append(Step("nfkc", nfkc))
    folded = nfkc.casefold()
    if folded != nfkc:
        steps.append(Step("casefold", folded))
    text = folded

    stripped, codes = _strip_corporate(text)
    if codes:
        if len(compact(stripped)) < MIN_KEY_LENGTH:
            steps.append(Step("guard:too_short", text))
        else:
            for code in codes:
                steps.append(Step(code, stripped))
            text = stripped

    for particle in KO_PARTICLES:
        if not text.endswith(particle):
            continue
        stem = text[: -len(particle)].rstrip()
        stem_key = compact(stem)
        if len(stem_key) < MIN_KEY_LENGTH:
            continue
        if stem_key in alias_map or stem_key in alias_map.values():
            detail = "alias"
        elif stem_key in known:
            detail = "graph"
        else:
            continue
        steps.append(Step("ko_particle:" + particle, stem, detail))
        text = stem
        break

    key = compact(text)
    if key != text:
        steps.append(Step("punct_space", key))
    if key in alias_map:
        key = alias_map[key]
        steps.append(Step("alias", key))

    return NormResult(key=key, rules=tuple(s.rule for s in steps), steps=tuple(steps))


def base_key(name: str) -> str:
    """Key without the graph-dependent steps (no particle removal, no alias)."""
    return normalize_name(name).key
