"""跨平台入口和路径行为测试。"""

from __future__ import annotations

from pathlib import PureWindowsPath
from typing import Any

from cursor_mcp_response_proxy.__main__ import _reconfigure_text_stream
from cursor_mcp_response_proxy.response_handler import _path_to_file_uri


class ReconfigurableStream:
    def __init__(self) -> None:
        self.options: dict[str, Any] | None = None

    def reconfigure(self, **options: Any) -> None:
        self.options = options


def test_text_stream_is_configured_for_utf8_and_lf() -> None:
    stream = ReconfigurableStream()

    _reconfigure_text_stream(stream, newline="\n")

    assert stream.options == {
        "encoding": "utf-8",
        "errors": "strict",
        "newline": "\n",
    }


def test_text_stream_without_reconfigure_is_ignored() -> None:
    _reconfigure_text_stream(object(), newline="\n")


def test_windows_path_is_converted_to_standard_file_uri() -> None:
    windows_path = PureWindowsPath(
        "C:/Users/Test User/AppData/Local/cursor-mcp-response-proxy/result.json"
    )

    assert _path_to_file_uri(windows_path) == (
        "file:///C:/Users/Test%20User/AppData/Local/"
        "cursor-mcp-response-proxy/result.json"
    )


def test_windows_unc_path_is_converted_to_standard_file_uri() -> None:
    windows_path = PureWindowsPath(
        "//file-server/shared results/cursor-mcp-response-proxy/result.json"
    )

    assert _path_to_file_uri(windows_path) == (
        "file://file-server/shared%20results/"
        "cursor-mcp-response-proxy/result.json"
    )
