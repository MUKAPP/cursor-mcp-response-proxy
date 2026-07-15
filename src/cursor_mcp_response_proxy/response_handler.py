"""保存并改写过大的 MCP 响应，避免 Cursor 截断正文。"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from .storage import save_payload

PROXY_METADATA_KEY = "_cursor_mcp_response_proxy"
MCP_METADATA_KEY = "_meta"
PASSTHROUGH_RESPONSE_METHODS = frozenset(
    {
        "initialize",
        "ping",
        "tools/list",
        "resources/list",
        "resources/templates/list",
        "resources/subscribe",
        "resources/unsubscribe",
        "prompts/list",
        "completion/complete",
        "logging/setLevel",
    }
)


def measure_message_chars(message: Any) -> int:
    """按紧凑 JSON 文本计算单条消息字符数。"""
    return len(json.dumps(message, ensure_ascii=False, separators=(",", ":")))


def _extract_request_method(
    request_message: dict[str, Any] | None,
) -> str | None:
    if not request_message:
        return None
    method = request_message.get("method")
    return method if isinstance(method, str) else None


def _extract_subject_name(
    request_message: dict[str, Any] | None,
) -> str | None:
    if not request_message:
        return None
    parameters = request_message.get("params")
    if not isinstance(parameters, dict):
        return None
    for key in ("name", "uri"):
        value = parameters.get(key)
        if isinstance(value, str):
            return value
    return None


def _truncate_text(text: str, preview_chars: int) -> str:
    if len(text) <= preview_chars:
        return text
    return text[:preview_chars] + "\n...[已截断]..."


def _collect_text_preview(payload: Any, preview_chars: int) -> str:
    """从常见 MCP 结果结构中提取易读文本预览。"""
    if isinstance(payload, str):
        return _truncate_text(payload, preview_chars)

    if isinstance(payload, dict):
        text_parts: list[str] = []
        for collection_key in ("content", "contents", "messages"):
            collection = payload.get(collection_key)
            if not isinstance(collection, list):
                continue
            for item in collection:
                if not isinstance(item, dict):
                    continue
                text = item.get("text")
                if isinstance(text, str):
                    text_parts.append(text)
                content = item.get("content")
                if isinstance(content, dict) and isinstance(content.get("text"), str):
                    text_parts.append(content["text"])
        if text_parts:
            return _truncate_text("\n\n".join(text_parts), preview_chars)

    serialized_payload = json.dumps(payload, ensure_ascii=False, indent=2)
    return _truncate_text(serialized_payload, preview_chars)


def _build_overflow_notice(
    *,
    saved_path: Path,
    original_chars: int,
    preview_chars: int,
    preview_text: str,
) -> str:
    return (
        "【cursor-mcp-response-proxy】上游响应超过 Cursor 的安全大小，"
        "完整内容已保存到本地文件。\n"
        f"- 本地文件: {saved_path}\n"
        f"- 原始字符数: {original_chars}\n"
        f"- 预览字符数: {preview_chars}\n"
        "- 如需完整内容，请读取上述文件。\n\n"
        "----- 预览开始 -----\n"
        f"{preview_text}\n"
        "----- 预览结束 -----\n"
    )


def _build_metadata(
    *,
    saved_path: Path,
    original_chars: int,
    preview_chars: int,
) -> dict[str, Any]:
    return {
        "truncated": True,
        "saved_path": str(saved_path),
        "original_chars": original_chars,
        "preview_chars": preview_chars,
    }


def _rewrite_result_for_method(
    message: dict[str, Any],
    *,
    request_method: str | None,
    notice: str,
    metadata: dict[str, Any],
    saved_path: Path,
    original_chars: int,
) -> dict[str, Any]:
    rewritten_message = copy.deepcopy(message)
    original_result = message.get("result")

    if request_method == "tools/call":
        rewritten_result: dict[str, Any] = {
            "content": [{"type": "text", "text": notice}],
            "isError": False,
            MCP_METADATA_KEY: {PROXY_METADATA_KEY: metadata},
        }
        if isinstance(original_result, dict) and "structuredContent" in original_result:
            rewritten_result[MCP_METADATA_KEY][PROXY_METADATA_KEY][
                "had_structured_content"
            ] = True
        rewritten_message["result"] = rewritten_result
        return rewritten_message

    if request_method == "resources/read":
        rewritten_message["result"] = {
            "contents": [
                {
                    "uri": f"file://{saved_path}",
                    "mimeType": "text/plain",
                    "text": notice,
                }
            ],
            MCP_METADATA_KEY: {PROXY_METADATA_KEY: metadata},
        }
        return rewritten_message

    if request_method == "prompts/get":
        rewritten_message["result"] = {
            "description": "上游提示词响应过大，完整内容已保存到本地文件。",
            "messages": [
                {
                    "role": "user",
                    "content": {"type": "text", "text": notice},
                }
            ],
            MCP_METADATA_KEY: {PROXY_METADATA_KEY: metadata},
        }
        return rewritten_message

    return {
        "jsonrpc": message.get("jsonrpc", "2.0"),
        "id": message.get("id"),
        "error": {
            "code": -32000,
            "message": f"上游响应过大，完整内容已保存到: {saved_path}",
            "data": {
                "saved_path": str(saved_path),
                "original_chars": original_chars,
            },
        },
    }


def maybe_truncate_message(
    message: Any,
    *,
    max_response_chars: int,
    preview_chars: int,
    output_dir: Path,
    request_message: dict[str, Any] | None = None,
) -> Any:
    """在超出安全阈值时保存原消息，并返回协议兼容的简短结果。"""
    if not isinstance(message, dict):
        return message

    original_chars = measure_message_chars(message)
    if original_chars <= max_response_chars:
        return message

    # 服务端主动请求需要客户端按原方法和参数作答，不能改写成通知或响应。
    if "id" in message and isinstance(message.get("method"), str):
        return message

    # 除日志通知外，其他通知都有各自的参数结构与状态语义，必须透明转发。
    message_method = message.get("method")
    if isinstance(message_method, str) and message_method != "notifications/message":
        return message

    request_method = _extract_request_method(request_message)
    if request_method in PASSTHROUGH_RESPONSE_METHODS:
        return message

    storage_method = request_method or (
        message_method if isinstance(message_method, str) else None
    )
    saved_path = save_payload(
        output_dir,
        message,
        method=storage_method,
        request_id=message.get("id"),
        subject_name=_extract_subject_name(request_message),
    )
    preview_source = message.get("result", message.get("error", message))
    preview_text = _collect_text_preview(preview_source, preview_chars)
    notice = _build_overflow_notice(
        saved_path=saved_path,
        original_chars=original_chars,
        preview_chars=preview_chars,
        preview_text=preview_text,
    )
    metadata = _build_metadata(
        saved_path=saved_path,
        original_chars=original_chars,
        preview_chars=preview_chars,
    )

    if "id" in message and "result" in message:
        return _rewrite_result_for_method(
            message,
            request_method=request_method,
            notice=notice,
            metadata=metadata,
            saved_path=saved_path,
            original_chars=original_chars,
        )

    if "id" in message and "error" in message:
        return {
            "jsonrpc": message.get("jsonrpc", "2.0"),
            "id": message.get("id"),
            "error": {
                "code": -32000,
                "message": f"上游错误响应过大，完整内容已保存到: {saved_path}",
                "data": {
                    "saved_path": str(saved_path),
                    "original_chars": original_chars,
                },
            },
        }

    return {
        "jsonrpc": "2.0",
        "method": "notifications/message",
        "params": {
            "level": "warning",
            "logger": "cursor-mcp-response-proxy",
            "data": notice,
            MCP_METADATA_KEY: {PROXY_METADATA_KEY: metadata},
        },
    }
