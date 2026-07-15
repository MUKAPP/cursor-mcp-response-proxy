"""过大 MCP 响应的本地存储。"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _safe_slug(value: str | None, fallback: str = "response") -> str:
    if not value:
        return fallback
    cleaned_value = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-._")
    return cleaned_value[:80] or fallback


def save_payload(
    output_dir: Path,
    payload: Any,
    *,
    method: str | None = None,
    request_id: Any = None,
    subject_name: str | None = None,
) -> Path:
    """将完整 JSON-RPC 消息写入本地文件并返回绝对路径。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    request_part = _safe_slug(
        str(request_id) if request_id is not None else None,
        "noid",
    )
    method_part = _safe_slug(method, "message")
    subject_part = _safe_slug(subject_name, "payload")
    target_path = output_dir / (
        f"{timestamp}_{method_part}_{subject_part}_{request_part}.json"
    )
    target_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return target_path.resolve()
