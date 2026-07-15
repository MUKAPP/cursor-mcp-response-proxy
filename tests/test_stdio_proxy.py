"""stdio 上游的进程级代理测试。"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from cursor_mcp_response_proxy.response_handler import (
    MCP_METADATA_KEY,
    PROXY_METADATA_KEY,
)


def test_stdio_proxy_forwards_and_saves_large_tool_result(tmp_path: Path) -> None:
    fixture_server = Path(__file__).parent / "fixtures" / "stdio_upstream_server.py"
    initialize_request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "proxy-test", "version": "1.0.0"},
        },
    }
    tool_request = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "return_text",
            "arguments": {"characters": 15_000},
        },
    }
    standard_input = "\n".join(
        json.dumps(message, separators=(",", ":"))
        for message in (initialize_request, tool_request)
    ) + "\n"

    completed_process = subprocess.run(
        [
            sys.executable,
            "-m",
            "cursor_mcp_response_proxy",
            "stdio",
            "--max-response-chars",
            "10000",
            "--preview-chars",
            "1000",
            "--output-dir",
            str(tmp_path),
            "--",
            sys.executable,
            str(fixture_server),
        ],
        input=standard_input,
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )

    response_messages = [
        json.loads(line)
        for line in completed_process.stdout.splitlines()
        if line.strip()
    ]
    assert [message["id"] for message in response_messages] == [1, 2]
    assert response_messages[0]["result"]["serverInfo"]["name"] == "test-upstream"

    tool_result = response_messages[1]["result"]
    metadata = tool_result[MCP_METADATA_KEY][PROXY_METADATA_KEY]
    saved_path = Path(metadata["saved_path"])
    assert metadata["truncated"] is True
    assert saved_path.exists()
    assert "本地文件" in tool_result["content"][0]["text"]

    saved_message = json.loads(saved_path.read_text(encoding="utf-8"))
    saved_text = saved_message["result"]["content"][0]["text"]
    assert len(saved_text) == 15_000
