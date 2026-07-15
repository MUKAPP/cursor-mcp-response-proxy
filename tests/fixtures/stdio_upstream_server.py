"""端到端测试使用的最小 stdio MCP 上游。"""

from __future__ import annotations

import json
import sys
from typing import Any


def build_response(message: dict[str, Any]) -> dict[str, Any] | None:
    request_id = message.get("id")
    if request_id is None:
        return None

    method = message.get("method")
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": "2025-11-25",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "test-upstream", "version": "1.0.0"},
            },
        }

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "tools": [
                    {
                        "name": "return_text",
                        "description": "返回指定长度的测试文本。",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"characters": {"type": "integer"}},
                            "required": ["characters"],
                        },
                    }
                ]
            },
        }

    if method == "tools/call":
        parameters = message.get("params")
        arguments = parameters.get("arguments", {}) if isinstance(parameters, dict) else {}
        characters = arguments.get("characters", 0)
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "content": [{"type": "text", "text": "x" * characters}],
                "isError": False,
            },
        }

    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": -32601, "message": "不支持的方法。"},
    }


def main() -> None:
    for raw_line in sys.stdin:
        message = json.loads(raw_line)
        response = build_response(message)
        if response is None:
            continue
        sys.stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
