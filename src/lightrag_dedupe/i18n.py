"""Two-language (English / Korean) message tables and language resolution.

Language order: ``--lang`` flag > ``LIGHTRAG_DEDUPE_LANG`` > ``LC_ALL`` > ``LC_MESSAGES`` > ``LANG``.
Anything that is not Korean (``ko`` or ``ko_*``) falls back to English.
Rule codes, JSON keys and CSV column names are not translated.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from functools import lru_cache
from importlib import resources

SUPPORTED = ("en", "ko")
ENV_VAR = "LIGHTRAG_DEDUPE_LANG"
_ENV_ORDER = (ENV_VAR, "LC_ALL", "LC_MESSAGES", "LANG")


def _is_korean(value: str) -> bool:
    v = value.strip().lower()
    return v == "ko" or v.startswith(("ko_", "ko-", "ko."))


def resolve_lang(cli_lang: str | None = None, env: Mapping[str, str] | None = None) -> str:
    """Pick ``"en"`` or ``"ko"``. The first non-empty source decides."""
    if cli_lang:
        return "ko" if _is_korean(cli_lang) else "en"
    environ = env if env is not None else {}
    for name in _ENV_ORDER:
        value = environ.get(name, "")
        if value.strip():
            return "ko" if _is_korean(value) else "en"
    return "en"


@lru_cache(maxsize=None)
def load_table(lang: str) -> dict[str, str]:
    """Load ``locales/<lang>.json`` (cached)."""
    text = resources.files("lightrag_dedupe").joinpath("locales", f"{lang}.json").read_text(encoding="utf-8")
    table = json.loads(text)
    return {str(k): str(v) for k, v in table.items()}


class Translator:
    """Callable that looks up a message by key and fills in keyword placeholders."""

    def __init__(self, lang: str = "en") -> None:
        self.lang = lang if lang in SUPPORTED else "en"
        self._table = load_table(self.lang)
        self._fallback = load_table("en")

    def __call__(self, key: str, /, **params: object) -> str:
        template = self._table.get(key) or self._fallback.get(key) or key
        try:
            return template.format(**params)
        except (KeyError, IndexError):
            return template
