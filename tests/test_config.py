"""通用代理命令行配置测试。"""

from __future__ import annotations

from pathlib import Path

from cursor_mcp_response_proxy.config import load_config


def test_stdio_config_parses_command_and_environment(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("UPSTREAM_TOKEN", "secret-value")

    config = load_config(
        [
            "stdio",
            "--output-dir",
            str(tmp_path),
            "--env",
            "TOKEN=${UPSTREAM_TOKEN}",
            "--",
            "python",
            "-m",
            "example_server",
        ]
    )

    assert config.transport_kind == "stdio"
    assert config.upstream_command == ("python", "-m", "example_server")
    assert config.upstream_environment == {"TOKEN": "secret-value"}
    assert config.max_response_chars == 10_000
    assert config.output_dir == tmp_path.resolve()


def test_streamable_http_config_expands_header_environment(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("REMOTE_TOKEN", "token-value")

    config = load_config(
        [
            "streamable-http",
            "--url",
            "https://example.com/mcp",
            "--header",
            "Authorization=Bearer ${REMOTE_TOKEN}",
            "--output-dir",
            str(tmp_path),
        ]
    )

    assert config.transport_kind == "streamable-http"
    assert config.remote_url == "https://example.com/mcp"
    assert config.headers == {"Authorization": "Bearer token-value"}


def test_sse_config_keeps_sse_read_timeout(tmp_path: Path) -> None:
    config = load_config(
        [
            "sse",
            "--url",
            "https://example.com/sse",
            "--sse-read-timeout",
            "45",
            "--output-dir",
            str(tmp_path),
        ]
    )

    assert config.transport_kind == "sse"
    assert config.sse_read_timeout_seconds == 45.0
