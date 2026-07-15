"""响应截断与落盘逻辑测试。"""

from __future__ import annotations

import json
from pathlib import Path

from mcp import types

from cursor_mcp_response_proxy.response_handler import (
    MCP_METADATA_KEY,
    PROXY_METADATA_KEY,
    maybe_truncate_message,
    measure_message_chars,
)


def test_small_message_passthrough(tmp_path: Path) -> None:
    message = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "content": [{"type": "text", "text": "hello"}],
            "isError": False,
        },
    }
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "web_search", "arguments": {}},
    }
    result = maybe_truncate_message(
        message,
        max_response_chars=10_000,
        preview_chars=100,
        output_dir=tmp_path,
        request_message=request,
    )
    assert result == message
    assert list(tmp_path.glob("*.json")) == []


def test_large_tools_call_is_saved_and_truncated(tmp_path: Path) -> None:
    huge_text = "A" * 5_000
    message = {
        "jsonrpc": "2.0",
        "id": 42,
        "result": {
            "content": [{"type": "text", "text": huge_text}],
            "isError": False,
        },
    }
    request = {
        "jsonrpc": "2.0",
        "id": 42,
        "method": "tools/call",
        "params": {"name": "extract_url", "arguments": {"url": "https://example.com"}},
    }
    original_chars = measure_message_chars(message)
    assert original_chars > 1_000

    result = maybe_truncate_message(
        message,
        max_response_chars=1_000,
        preview_chars=200,
        output_dir=tmp_path,
        request_message=request,
    )

    assert result["id"] == 42
    assert "result" in result
    assert result["result"]["isError"] is False
    meta = result["result"][MCP_METADATA_KEY][PROXY_METADATA_KEY]
    assert meta["truncated"] is True
    saved_path = Path(meta["saved_path"])
    assert saved_path.exists()
    saved = json.loads(saved_path.read_text(encoding="utf-8"))
    assert saved["result"]["content"][0]["text"] == huge_text

    preview = result["result"]["content"][0]["text"]
    assert "本地文件" in preview
    assert str(saved_path) in preview
    assert measure_message_chars(result) < original_chars
    types.CallToolResult.model_validate(result["result"])


def test_large_resource_result_keeps_resource_shape(tmp_path: Path) -> None:
    message = {
        "jsonrpc": "2.0",
        "id": 8,
        "result": {
            "contents": [
                {
                    "uri": "file:///large.txt",
                    "mimeType": "text/plain",
                    "text": "R" * 5_000,
                }
            ]
        },
    }
    request = {
        "jsonrpc": "2.0",
        "id": 8,
        "method": "resources/read",
        "params": {"uri": "file:///large.txt"},
    }

    result = maybe_truncate_message(
        message,
        max_response_chars=1_000,
        preview_chars=200,
        output_dir=tmp_path,
        request_message=request,
    )

    assert result["result"]["contents"][0]["uri"].startswith("file://")
    assert "本地文件" in result["result"]["contents"][0]["text"]
    metadata = result["result"][MCP_METADATA_KEY][PROXY_METADATA_KEY]
    assert metadata["truncated"] is True
    types.ReadResourceResult.model_validate(result["result"])


def test_large_prompt_result_keeps_prompt_shape(tmp_path: Path) -> None:
    message = {
        "jsonrpc": "2.0",
        "id": 9,
        "result": {
            "messages": [
                {
                    "role": "user",
                    "content": {"type": "text", "text": "P" * 5_000},
                }
            ]
        },
    }
    request = {
        "jsonrpc": "2.0",
        "id": 9,
        "method": "prompts/get",
        "params": {"name": "large-prompt"},
    }

    result = maybe_truncate_message(
        message,
        max_response_chars=1_000,
        preview_chars=200,
        output_dir=tmp_path,
        request_message=request,
    )

    assert result["result"]["messages"][0]["role"] == "user"
    assert "本地文件" in result["result"]["messages"][0]["content"]["text"]
    metadata = result["result"][MCP_METADATA_KEY][PROXY_METADATA_KEY]
    assert metadata["truncated"] is True
    types.GetPromptResult.model_validate(result["result"])


def test_unknown_large_result_becomes_json_rpc_error(tmp_path: Path) -> None:
    message = {
        "jsonrpc": "2.0",
        "id": 10,
        "result": {"value": "U" * 5_000},
    }
    request = {
        "jsonrpc": "2.0",
        "id": 10,
        "method": "custom/read",
        "params": {},
    }

    result = maybe_truncate_message(
        message,
        max_response_chars=1_000,
        preview_chars=200,
        output_dir=tmp_path,
        request_message=request,
    )

    assert "result" not in result
    assert result["error"]["code"] == -32000
    assert Path(result["error"]["data"]["saved_path"]).exists()


def test_large_server_request_is_forwarded_unchanged(tmp_path: Path) -> None:
    server_request = {
        "jsonrpc": "2.0",
        "id": "server-request-1",
        "method": "sampling/createMessage",
        "params": {"prompt": "S" * 5_000},
    }

    result = maybe_truncate_message(
        server_request,
        max_response_chars=1_000,
        preview_chars=200,
        output_dir=tmp_path,
    )

    assert result == server_request
    assert list(tmp_path.glob("*.json")) == []


def test_large_progress_notification_is_forwarded_unchanged(tmp_path: Path) -> None:
    notification = {
        "jsonrpc": "2.0",
        "method": "notifications/progress",
        "params": {
            "progressToken": "task-1",
            "progress": 1,
            "total": 2,
            "message": "N" * 5_000,
        },
    }

    result = maybe_truncate_message(
        notification,
        max_response_chars=1_000,
        preview_chars=200,
        output_dir=tmp_path,
    )

    assert result == notification
    assert list(tmp_path.glob("*.json")) == []
