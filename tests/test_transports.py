"""上游传输适配器测试。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest

from cursor_mcp_response_proxy.config import ProxyConfig
from cursor_mcp_response_proxy.transports import open_upstream_transport


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def build_http_config(
    tmp_path: Path,
    *,
    transport_kind: str,
) -> ProxyConfig:
    return ProxyConfig(
        transport_kind=transport_kind,
        max_response_chars=10_000,
        preview_chars=4_000,
        output_dir=tmp_path,
        timeout_seconds=12.0,
        sse_read_timeout_seconds=34.0,
        headers={"Authorization": "Bearer test"},
        remote_url="https://example.com/mcp",
    )


@pytest.mark.anyio
async def test_sse_transport_passes_url_headers_and_timeouts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    captured_arguments: dict[str, Any] = {}
    receive_stream = object()
    send_stream = object()

    @asynccontextmanager
    async def fake_sse_client(
        url: str,
        *,
        headers: dict[str, str],
        timeout: float,
        sse_read_timeout: float,
    ):
        captured_arguments.update(
            {
                "url": url,
                "headers": headers,
                "timeout": timeout,
                "sse_read_timeout": sse_read_timeout,
            }
        )
        yield receive_stream, send_stream

    monkeypatch.setattr(
        "cursor_mcp_response_proxy.transports.sse_client",
        fake_sse_client,
    )
    config = build_http_config(tmp_path, transport_kind="sse")

    async with open_upstream_transport(config) as streams:
        assert streams == (receive_stream, send_stream)

    assert captured_arguments == {
        "url": "https://example.com/mcp",
        "headers": {"Authorization": "Bearer test"},
        "timeout": 12.0,
        "sse_read_timeout": 34.0,
    }


@pytest.mark.anyio
async def test_streamable_http_transport_uses_custom_http_client(
    tmp_path: Path,
    monkeypatch,
) -> None:
    captured_arguments: dict[str, Any] = {}
    receive_stream = object()
    send_stream = object()

    class FakeAsyncClient:
        def __init__(self, **arguments: Any) -> None:
            captured_arguments["client_arguments"] = arguments

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *exception_details: Any) -> None:
            return None

    @asynccontextmanager
    async def fake_streamable_http_client(
        url: str,
        *,
        http_client: FakeAsyncClient,
        terminate_on_close: bool,
    ):
        captured_arguments.update(
            {
                "url": url,
                "http_client": http_client,
                "terminate_on_close": terminate_on_close,
            }
        )
        yield receive_stream, send_stream, lambda: "session-id"

    monkeypatch.setattr(
        "cursor_mcp_response_proxy.transports.httpx.AsyncClient",
        FakeAsyncClient,
    )
    monkeypatch.setattr(
        "cursor_mcp_response_proxy.transports.streamable_http_client",
        fake_streamable_http_client,
    )
    config = build_http_config(tmp_path, transport_kind="streamable-http")

    async with open_upstream_transport(config) as streams:
        assert streams == (receive_stream, send_stream)

    assert captured_arguments["url"] == "https://example.com/mcp"
    assert captured_arguments["terminate_on_close"] is True
    client_arguments = captured_arguments["client_arguments"]
    assert client_arguments["headers"] == {"Authorization": "Bearer test"}
    assert client_arguments["follow_redirects"] is True
    assert client_arguments["timeout"].connect == 12.0
    assert client_arguments["timeout"].read == 34.0
