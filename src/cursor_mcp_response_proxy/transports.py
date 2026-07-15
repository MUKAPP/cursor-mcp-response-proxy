"""基于官方 MCP SDK 的三种上游客户端传输。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TypeAlias

import httpx
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from mcp.client.sse import sse_client
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.message import SessionMessage

from .config import ProxyConfig

UpstreamReceiveStream: TypeAlias = MemoryObjectReceiveStream[SessionMessage | Exception]
UpstreamSendStream: TypeAlias = MemoryObjectSendStream[SessionMessage]
UpstreamStreams: TypeAlias = tuple[UpstreamReceiveStream, UpstreamSendStream]


@asynccontextmanager
async def open_upstream_transport(
    config: ProxyConfig,
) -> AsyncIterator[UpstreamStreams]:
    """按配置打开上游，并统一返回双向 MCP 消息流。"""
    if config.transport_kind == "stdio":
        command = config.upstream_command[0]
        arguments = list(config.upstream_command[1:])
        parameters = StdioServerParameters(
            command=command,
            args=arguments,
            env=config.upstream_environment,
            cwd=config.upstream_cwd,
        )
        async with stdio_client(parameters) as streams:
            yield streams
        return

    if config.remote_url is None:
        raise ValueError("HTTP 上游缺少 URL")

    if config.transport_kind == "sse":
        async with sse_client(
            config.remote_url,
            headers=config.headers,
            timeout=config.timeout_seconds,
            sse_read_timeout=config.sse_read_timeout_seconds,
        ) as streams:
            yield streams
        return

    timeout = httpx.Timeout(
        config.timeout_seconds,
        read=config.sse_read_timeout_seconds,
    )
    async with httpx.AsyncClient(
        headers=config.headers,
        timeout=timeout,
        follow_redirects=True,
    ) as http_client:
        async with streamable_http_client(
            config.remote_url,
            http_client=http_client,
            terminate_on_close=True,
        ) as streams:
            receive_stream, send_stream, _get_session_id = streams
            yield receive_stream, send_stream
