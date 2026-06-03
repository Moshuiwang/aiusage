from __future__ import annotations

import json
from typing import Any, Dict
from urllib import error, request


def push_limits_payload(url: str, token: str, payload: Dict[str, Any], timeout: float = 10.0) -> Dict[str, Any]:
    if not url:
        raise ValueError("push url is required")
    if not token:
        raise ValueError("push token is required")

    body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    req = request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with request.urlopen(req, timeout=timeout) as response:
            response_body = response.read().decode("utf-8")
    except error.HTTPError as exc:
        response_body = exc.read().decode("utf-8", errors="replace")
        raise ValueError(f"limits push failed with HTTP {exc.code}: {_safe_response_message(response_body)}") from exc
    except error.URLError as exc:
        raise ValueError(f"limits push failed: {exc.reason}") from exc

    try:
        parsed = json.loads(response_body)
    except json.JSONDecodeError as exc:
        raise ValueError("limits push response is not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("limits push response must be a JSON object")
    return parsed


def _safe_response_message(body: str) -> str:
    message = body.replace("\n", " ").strip()
    return message[:300]
