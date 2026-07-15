"""stdio 上游的进程级代理测试。"""

from __future__ import annotations

import json
import queue
import subprocess
import sys
import threading
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
    proxy_process = subprocess.Popen(
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
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )

    assert proxy_process.stdin is not None
    assert proxy_process.stdout is not None
    assert proxy_process.stderr is not None

    response_lines: queue.Queue[str] = queue.Queue()

    def read_proxy_output() -> None:
        for line in proxy_process.stdout:
            if line.strip():
                response_lines.put(line)

    output_reader = threading.Thread(target=read_proxy_output, daemon=True)
    output_reader.start()

    try:
        response_messages = []
        for request_message in (initialize_request, tool_request):
            proxy_process.stdin.write(
                json.dumps(request_message, separators=(",", ":")) + "\n"
            )
            proxy_process.stdin.flush()
            response_messages.append(
                json.loads(response_lines.get(timeout=10))
            )
    finally:
        proxy_process.stdin.close()
        proxy_process.wait(timeout=10)
        output_reader.join(timeout=10)

    proxy_stderr = proxy_process.stderr.read()
    assert proxy_process.returncode == 0, proxy_stderr
    assert [message["id"] for message in response_messages] == [1, 2]
    assert response_messages[0]["result"]["serverInfo"]["name"] == "test-upstream"

    tool_result = response_messages[1]["result"]
    metadata = tool_result[MCP_METADATA_KEY][PROXY_METADATA_KEY]
    saved_path = Path(metadata["saved_path"])
    assert metadata["truncated"] is True
    assert saved_path.exists()
    assert "响应过大，已保存到临时文件" in tool_result["content"][0]["text"]

    saved_message = json.loads(saved_path.read_text(encoding="utf-8"))
    saved_text = saved_message["result"]["content"][0]["text"]
    assert len(saved_text) == 15_000
