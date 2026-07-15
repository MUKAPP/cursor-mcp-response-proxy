"""Cursor stdio 与上游 MCP 消息流之间的异步代理。"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any, TextIO

import anyio
from anyio import CancelScope
from mcp import types
from mcp.shared.message import SessionMessage

from .config import ProxyConfig
from .response_handler import maybe_truncate_message
from .transports import (
    UpstreamReceiveStream,
    UpstreamSendStream,
    open_upstream_transport,
)

logger = logging.getLogger("cursor_mcp_response_proxy")


def _message_to_dict(session_message: SessionMessage) -> dict[str, Any]:
    message = session_message.message.model_dump(
        by_alias=True,
        mode="json",
        exclude_none=True,
    )
    if not isinstance(message, dict):
        raise TypeError("MCP 消息序列化结果不是 JSON 对象")
    return message


def _is_response(message: dict[str, Any]) -> bool:
    return "id" in message and "method" not in message and (
        "result" in message or "error" in message
    )


class CursorMcpResponseProxy:
    """从 Cursor stdin 读取消息，并将上游消息安全写回 stdout。"""

    def __init__(self, config: ProxyConfig) -> None:
        self._config = config
        self._pending_requests: dict[Any, dict[str, Any]] = {}
        self._write_lock = anyio.Lock()

    async def run(
        self,
        stdin: TextIO | None = None,
        stdout: TextIO | None = None,
    ) -> None:
        input_stream = stdin if stdin is not None else sys.stdin
        output_stream = stdout if stdout is not None else sys.stdout

        logger.info(
            "代理已启动: transport=%s output_dir=%s max_chars=%s preview_chars=%s",
            self._config.transport_kind,
            self._config.output_dir,
            self._config.max_response_chars,
            self._config.preview_chars,
        )

        async with open_upstream_transport(self._config) as (
            upstream_receive_stream,
            upstream_send_stream,
        ):
            async with anyio.create_task_group() as task_group:
                task_group.start_soon(
                    self._forward_cursor_messages_and_stop,
                    input_stream,
                    upstream_send_stream,
                    task_group.cancel_scope,
                )
                task_group.start_soon(
                    self._forward_upstream_messages_and_stop,
                    upstream_receive_stream,
                    output_stream,
                    task_group.cancel_scope,
                )

    async def _forward_cursor_messages_and_stop(
        self,
        input_stream: TextIO,
        upstream_send_stream: UpstreamSendStream,
        cancel_scope: CancelScope,
    ) -> None:
        try:
            await self._forward_cursor_messages(input_stream, upstream_send_stream)

            # stdin 关闭通常表示 Cursor 正在停止服务器。先等待已发出的请求完成，
            # 再关闭 SDK 写流，否则 HTTP 传输可能同时关闭接收流并丢失最后响应。
            with anyio.move_on_after(10.0):
                while self._pending_requests:
                    await anyio.sleep(0.01)
        finally:
            await upstream_send_stream.aclose()
            cancel_scope.cancel()

    async def _forward_upstream_messages_and_stop(
        self,
        upstream_receive_stream: UpstreamReceiveStream,
        output_stream: TextIO,
        cancel_scope: CancelScope,
    ) -> None:
        try:
            await self._forward_upstream_messages(
                upstream_receive_stream,
                output_stream,
            )
        finally:
            cancel_scope.cancel()

    async def _forward_cursor_messages(
        self,
        input_stream: TextIO,
        upstream_send_stream: UpstreamSendStream,
    ) -> None:
        async_input = anyio.wrap_file(input_stream)
        while True:
            raw_line = await async_input.readline()
            if not raw_line:
                break
            line = raw_line.strip()
            if not line:
                continue

            try:
                message = json.loads(line)
            except json.JSONDecodeError as error:
                logger.error("无法解析 stdin JSON: %s (%s)", line[:200], error)
                continue
            if not isinstance(message, dict):
                logger.error("stdin 消息不是 JSON 对象: %s", type(message).__name__)
                continue

            request_id = message.get("id")
            method = message.get("method")
            if request_id is not None and isinstance(method, str):
                self._pending_requests[request_id] = message

            try:
                validated_message = types.JSONRPCMessage.model_validate(message)
            except Exception as error:
                logger.error("stdin 消息不符合 JSON-RPC: %s", error)
                self._pending_requests.pop(request_id, None)
                continue

            logger.debug("-> 上游 method=%s id=%s", method, request_id)
            await upstream_send_stream.send(SessionMessage(validated_message))

    async def _forward_upstream_messages(
        self,
        upstream_receive_stream: UpstreamReceiveStream,
        output_stream: TextIO,
    ) -> None:
        async with upstream_receive_stream:
            async for received_item in upstream_receive_stream:
                if isinstance(received_item, Exception):
                    await self._write_transport_errors(received_item, output_stream)
                    continue

                upstream_message = _message_to_dict(received_item)
                related_request = None
                if _is_response(upstream_message):
                    related_request = self._pending_requests.pop(
                        upstream_message.get("id"),
                        None,
                    )

                processed_message = maybe_truncate_message(
                    upstream_message,
                    max_response_chars=self._config.max_response_chars,
                    preview_chars=self._config.preview_chars,
                    output_dir=self._config.output_dir,
                    request_message=related_request,
                )
                await self._write_message(processed_message, output_stream)

    async def _write_transport_errors(
        self,
        error: Exception,
        output_stream: TextIO,
    ) -> None:
        error_message = f"上游传输失败: {error}"
        logger.error(error_message)
        pending_requests = list(self._pending_requests.items())
        self._pending_requests.clear()

        if not pending_requests:
            await self._write_message(
                {
                    "jsonrpc": "2.0",
                    "method": "notifications/message",
                    "params": {
                        "level": "error",
                        "logger": "cursor-mcp-response-proxy",
                        "data": error_message,
                    },
                },
                output_stream,
            )
            return

        for request_id, _request_message in pending_requests:
            await self._write_message(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": -32000,
                        "message": error_message,
                    },
                },
                output_stream,
            )

    async def _write_message(
        self,
        message: Any,
        output_stream: TextIO,
    ) -> None:
        line = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
        async with self._write_lock:
            await anyio.to_thread.run_sync(output_stream.write, line + "\n")
            await anyio.to_thread.run_sync(output_stream.flush)
        logger.debug(
            "<- Cursor chars=%s id=%s",
            len(line),
            message.get("id") if isinstance(message, dict) else None,
        )
