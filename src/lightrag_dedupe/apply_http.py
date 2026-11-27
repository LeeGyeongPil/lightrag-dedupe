"""Merge through a running LightRAG server (``POST /graph/entities/merge``), standard library only."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .errors import ApplyError, UsageError

API_KEY_ENV = "LIGHTRAG_API_KEY"
DEFAULT_TIMEOUT = 600.0  # merges re-embed entities; a slow embedding backend is not an error


class LightRagClient:
    """Tiny client for the two endpoints this tool needs."""

    def __init__(self, base_url: str, api_key: str | None = None, timeout: float = DEFAULT_TIMEOUT) -> None:
        parsed = urllib.parse.urlparse(base_url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise UsageError("err.server_url", url=base_url)
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or None
        self.timeout = timeout

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
        req = urllib.request.Request(self.base_url + path, data=data, method=method)
        req.add_header("Accept", "application/json")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        if self.api_key:
            req.add_header("X-API-Key", self.api_key)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310 (scheme checked above)
                payload = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = _error_detail(exc)
            if exc.code == 409:
                raise ApplyError("err.server_busy", detail=detail) from exc
            raise ApplyError("err.server_http", status=exc.code, detail=detail) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ApplyError("err.server_unreachable", url=self.base_url, detail=str(exc)) from exc
        try:
            parsed = json.loads(payload) if payload else {}
        except ValueError:
            parsed = {}
        return parsed if isinstance(parsed, dict) else {}

    def entity_exists(self, name: str) -> bool:
        query = urllib.parse.urlencode({"name": name})
        return bool(self._request("GET", f"/graph/entity/exists?{query}").get("exists"))

    def merge(self, sources: list[str], target: str) -> dict[str, Any]:
        return self._request(
            "POST",
            "/graph/entities/merge",
            {"entities_to_change": list(sources), "entity_to_change_into": target},
        )


def _error_detail(exc: urllib.error.HTTPError) -> str:
    try:
        raw = exc.read().decode("utf-8", errors="replace")
    except OSError:
        return ""
    try:
        data = json.loads(raw)
    except ValueError:
        return raw.strip()[:300]
    if isinstance(data, dict) and "detail" in data:
        return str(data["detail"])[:300]
    return raw.strip()[:300]
