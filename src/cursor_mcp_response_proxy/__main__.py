"""cursor-mcp-response-proxy 命令行入口。"""

from __future__ import annotations

import logging
import sys

import anyio

from .config import load_config
from .proxy import CursorMcpResponseProxy


def main(argv: list[str] | None = None) -> None:
    """加载配置并运行 Cursor stdio 代理。"""
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
