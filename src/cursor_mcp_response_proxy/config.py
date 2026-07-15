"""通用 MCP 响应代理的命令行与环境变量配置。"""

from __future__ import annotations

import argparse
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

TransportKind = Literal["stdio", "sse", "streamable-http"]

DEFAULT_MAX_RESPONSE_CHARS = 10_000
DEFAULT_PREVIEW_CHARS = 4_000
DEFAULT_TIMEOUT_SECONDS = 120.0
DEFAULT_SSE_READ_TIMEOUT_SECONDS = 300.0
ENVIRONMENT_PREFIX = "CURSOR_MCP_RESPONSE_PROXY_"
UNRESOLVED_ENVIRONMENT_VARIABLE = re.compile(r"\$\{[^}]+\}")


@dataclass(frozen=True)
class ProxyConfig:
    """Cursor stdio 入口与上游 MCP 传输的完整运行配置。"""

    transport_kind: TransportKind
    max_response_chars: int
    preview_chars: int
    output_dir: Path
    timeout_seconds: float
    sse_read_timeout_seconds: float
    headers: dict[str, str]
    remote_url: str | None = None
    upstream_command: tuple[str, ...] = ()
    upstream_environment: dict[str, str] | None = None
    upstream_cwd: Path | None = None


def _parse_positive_int(raw_value: str, field_name: str) -> int:
    try:
        parsed_value = int(raw_value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"{field_name} 必须是整数") from error
    if parsed_value <= 0:
        raise argparse.ArgumentTypeError(f"{field_name} 必须大于 0")
    return parsed_value


def _parse_positive_float(raw_value: str, field_name: str) -> float:
    try:
        parsed_value = float(raw_value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"{field_name} 必须是数字") from error
    if parsed_value <= 0:
        raise argparse.ArgumentTypeError(f"{field_name} 必须大于 0")
    return parsed_value


def _parse_name_value(
    raw_value: str,
    *,
    field_name: str,
) -> tuple[str, str]:
    name, separator, value = raw_value.partition("=")
    if not separator or not name.strip():
        raise argparse.ArgumentTypeError(f"{field_name} 必须使用 NAME=VALUE 格式")

    expanded_value = os.path.expandvars(value)
    if UNRESOLVED_ENVIRONMENT_VARIABLE.search(expanded_value):
        raise argparse.ArgumentTypeError(
            f"{field_name} 引用了不存在的环境变量: {raw_value}"
        )
    return name.strip(), expanded_value


def _parse_headers(raw_headers: list[str]) -> dict[str, str]:
    headers: dict[str, str] = {}
    for raw_header in raw_headers:
        name, value = _parse_name_value(raw_header, field_name="header")
        headers[name] = value
    return headers


def _parse_environment(raw_environment: list[str]) -> dict[str, str] | None:
    if not raw_environment:
        return None

    environment: dict[str, str] = {}
    for raw_variable in raw_environment:
        name, value = _parse_name_value(raw_variable, field_name="env")
        environment[name] = value
    return environment


def _add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--max-response-chars",
        type=lambda value: _parse_positive_int(value, "max-response-chars"),
        default=int(
            os.environ.get(
                f"{ENVIRONMENT_PREFIX}MAX_RESPONSE_CHARS",
                DEFAULT_MAX_RESPONSE_CHARS,
            )
        ),
        help=(
            "单条 JSON-RPC 响应超过该字符数时保存完整内容并返回预览 "
            f"（默认: {DEFAULT_MAX_RESPONSE_CHARS}）"
        ),
    )
    parser.add_argument(
        "--preview-chars",
        type=lambda value: _parse_positive_int(value, "preview-chars"),
        default=int(
            os.environ.get(
                f"{ENVIRONMENT_PREFIX}PREVIEW_CHARS",
                DEFAULT_PREVIEW_CHARS,
            )
        ),
        help=f"返回给 Cursor 的预览字符数（默认: {DEFAULT_PREVIEW_CHARS}）",
    )
    parser.add_argument(
        "--output-dir",
        default=os.environ.get(
            f"{ENVIRONMENT_PREFIX}OUTPUT_DIR",
            str(Path.home() / ".cache" / "cursor-mcp-response-proxy"),
        ),
        help="完整响应保存目录（默认: ~/.cache/cursor-mcp-response-proxy）",
    )


def _add_http_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--url", required=True, help="上游 MCP 端点 URL")
    parser.add_argument(
        "--header",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="发送给上游的请求头；可重复，VALUE 支持 ${ENV_VAR}",
    )
    parser.add_argument(
        "--timeout",
        type=lambda value: _parse_positive_float(value, "timeout"),
        default=float(
            os.environ.get(
                f"{ENVIRONMENT_PREFIX}TIMEOUT_SECONDS",
                DEFAULT_TIMEOUT_SECONDS,
            )
        ),
        help=f"常规 HTTP 操作超时秒数（默认: {DEFAULT_TIMEOUT_SECONDS}）",
    )
    parser.add_argument(
        "--sse-read-timeout",
        type=lambda value: _parse_positive_float(value, "sse-read-timeout"),
        default=float(
            os.environ.get(
                f"{ENVIRONMENT_PREFIX}SSE_READ_TIMEOUT_SECONDS",
                DEFAULT_SSE_READ_TIMEOUT_SECONDS,
            )
        ),
        help=(
            "等待 SSE 新事件的超时秒数 "
            f"（默认: {DEFAULT_SSE_READ_TIMEOUT_SECONDS}）"
        ),
    )


def build_argument_parser() -> argparse.ArgumentParser:
    """构造包含三种上游传输子命令的参数解析器。"""
    parser = argparse.ArgumentParser(
        prog="cursor-mcp-response-proxy",
        description=(
            "Cursor MCP stdio 响应代理：连接 stdio、SSE 或 Streamable HTTP "
            "上游，并保护过大的响应。"
        ),
    )
    subparsers = parser.add_subparsers(dest="transport_kind", required=True)

    stdio_parser = subparsers.add_parser("stdio", help="启动本地 stdio MCP 上游")
    _add_common_arguments(stdio_parser)
    stdio_parser.add_argument(
        "--cwd",
        help="上游进程工作目录",
    )
    stdio_parser.add_argument(
        "--env",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="传给上游进程的环境变量；可重复，VALUE 支持 ${ENV_VAR}",
    )
    stdio_parser.add_argument(
        "upstream_command",
        nargs=argparse.REMAINDER,
        help="放在 -- 后的上游命令及参数",
    )

    sse_parser = subparsers.add_parser("sse", help="连接传统 MCP SSE 上游")
    _add_common_arguments(sse_parser)
    _add_http_arguments(sse_parser)

    streamable_http_parser = subparsers.add_parser(
        "streamable-http",
        help="连接 MCP Streamable HTTP 上游",
    )
    _add_common_arguments(streamable_http_parser)
    _add_http_arguments(streamable_http_parser)
    return parser


def load_config(argv: list[str] | None = None) -> ProxyConfig:
    """解析参数、展开环境变量并完成跨字段校验。"""
    parser = build_argument_parser()
    arguments = parser.parse_args(argv)

    if arguments.preview_chars >= arguments.max_response_chars:
        parser.error("--preview-chars 必须小于 --max-response-chars")

    output_dir = Path(arguments.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if arguments.transport_kind == "stdio":
        upstream_command = list(arguments.upstream_command)
        if upstream_command and upstream_command[0] == "--":
            upstream_command.pop(0)
        if not upstream_command:
            parser.error("stdio 子命令必须在 -- 后提供上游命令")

        try:
            upstream_environment = _parse_environment(arguments.env)
        except argparse.ArgumentTypeError as error:
            parser.error(str(error))

        return ProxyConfig(
            transport_kind="stdio",
            max_response_chars=arguments.max_response_chars,
            preview_chars=arguments.preview_chars,
            output_dir=output_dir,
            timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
            sse_read_timeout_seconds=DEFAULT_SSE_READ_TIMEOUT_SECONDS,
            headers={},
            upstream_command=tuple(upstream_command),
            upstream_environment=upstream_environment,
            upstream_cwd=(
                Path(arguments.cwd).expanduser().resolve()
                if arguments.cwd
                else None
            ),
        )

    try:
        headers = _parse_headers(arguments.header)
    except argparse.ArgumentTypeError as error:
        parser.error(str(error))

    return ProxyConfig(
        transport_kind=arguments.transport_kind,
        max_response_chars=arguments.max_response_chars,
        preview_chars=arguments.preview_chars,
        output_dir=output_dir,
        timeout_seconds=arguments.timeout,
        sse_read_timeout_seconds=arguments.sse_read_timeout,
        headers=headers,
        remote_url=arguments.url,
    )
