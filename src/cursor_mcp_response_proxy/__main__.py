"""cursor-mcp-response-proxy 命令行入口。"""

from __future__ import annotations

import logging
import sys
from typing import Any

import anyio

from .config import load_config
from .proxy import CursorMcpResponseProxy


def _reconfigure_text_stream(
    stream: Any,
    *,
    newline: str | None = None,
) -> None:
    """在支持 reconfigure 的标准文本流上统一使用 UTF-8。"""
    reconfigure = getattr(stream, "reconfigure", None)
    if not callable(reconfigure):
        return

    options: dict[str, Any] = {
        "encoding": "utf-8",
        "errors": "strict",
    }
    if newline is not None:
        options["newline"] = newline
    reconfigure(**options)


def configure_standard_streams() -> None:
    """配置跨平台 MCP stdio 编码与换行行为。"""
    _reconfigure_text_stream(sys.stdin)
    _reconfigure_text_stream(sys.stdout, newline="\n")
    _reconfigure_text_stream(sys.stderr, newline="\n")


def main(argv: list[str] | None = None) -> None:
    """加载配置并运行 Cursor stdio 代理。"""
    configure_standard_streams()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )
    config = load_config(argv)
    proxy = CursorMcpResponseProxy(config)
    try:
        anyio.run(proxy.run)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
