# cursor-mcp-response-proxy

面向 Cursor 的本地 MCP stdio 响应代理。代理入口固定为 stdio，上游可以是：

- 本地 stdio MCP 服务器
- 传统 SSE MCP 服务器
- Streamable HTTP MCP 服务器

当单条上游响应超过安全阈值时，代理会保存完整 JSON-RPC 消息，并向 Cursor 返回较短的预览和文件路径，避免正文被丢弃。

## 背景

Cursor 对 MCP 工具结果有大小限制。当返回内容超出限制太多时，Cursor 可能会直接丢弃整个结果，而不是截断正文，也不会自动将完整内容保存到文件并把文件路径提供给 Agent。此时上游 MCP 工具虽然已经成功执行，Agent 仍然无法读取结果，也不知道完整内容可以从哪里获取。

在 Cursor 环境中实测，单次 MCP 工具结果最多可完整返回约 `12000` 个 ASCII 字符，从第 `12001` 个字符开始会发生截断。考虑到实际响应还包含 JSON-RPC 包装、字段信息，并可能使用多字节字符，本项目将默认安全阈值设置为 `10000` 个字符，为这些额外内容和不同 Cursor 版本的行为留出余量。

本项目用于在响应到达 Cursor 之前处理这个问题：代理检测单条 JSON-RPC 响应的大小，超过安全阈值时先将完整响应保存到本地文件，再向 Cursor 返回较短的预览、原始字符数和文件路径。这样 Agent 能继续使用预览，并在需要时读取完整文件。

```text
Cursor (stdio)
    <-> cursor-mcp-response-proxy
        <-> stdio | SSE | Streamable HTTP 上游
```

## 安装

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
pip install pytest
```

验证：

```bash
PYTHONPATH=src pytest
cursor-mcp-response-proxy --help
```

## 默认响应保护


| 配置                     | 默认值                                  |
| ---------------------- | ------------------------------------ |
| `--max-response-chars` | `10000`                              |
| `--preview-chars`      | `4000`                               |
| `--output-dir`         | `~/.cache/cursor-mcp-response-proxy` |


阈值按整条紧凑 JSON-RPC 消息的字符数计算。超过阈值时：

1. 完整原始消息保存为 JSON 文件。
2. `tools/call`、`resources/read`、`prompts/get` 返回符合各自协议结构的预览。
3. 代理信息放在标准 `_meta._cursor_mcp_response_proxy` 字段中。
4. 其他未知响应返回 JSON-RPC 错误，并提供完整文件路径。

## Cursor 配置

以下示例假设项目位于 `/path/to/cursor-mcp-response-proxy`。

### Streamable HTTP

Anysearch 示例：

```json
{
  "mcpServers": {
    "anysearch": {
      "command": "/path/to/cursor-mcp-response-proxy/.venv/bin/cursor-mcp-response-proxy",
      "args": [
        "streamable-http",
        "--url",
        "https://api.anysearch.com/mcp",
        "--header",
        "Authorization=Bearer ${ANYSEARCH_API_KEY}"
      ],
      "env": {
        "ANYSEARCH_API_KEY": "你的_API_KEY"
      }
    }
  }
}
```

`${ANYSEARCH_API_KEY}` 由代理启动时展开。不要把真实密钥写入仓库。

### SSE

```json
{
  "mcpServers": {
    "legacy-sse": {
      "command": "/path/to/cursor-mcp-response-proxy/.venv/bin/cursor-mcp-response-proxy",
      "args": [
        "sse",
        "--url",
        "https://example.com/sse",
        "--header",
        "Authorization=Bearer ${MCP_TOKEN}"
      ],
      "env": {
        "MCP_TOKEN": "你的令牌"
      }
    }
  }
}
```

### stdio

上游命令放在 `--` 后：

```json
{
  "mcpServers": {
    "local-server": {
      "command": "/path/to/cursor-mcp-response-proxy/.venv/bin/cursor-mcp-response-proxy",
      "args": [
        "stdio",
        "--",
        "python",
        "-m",
        "example_mcp_server"
      ]
    }
  }
}
```

需要传递环境变量时可重复使用 `--env NAME=VALUE`。代理仅把这些变量与 SDK 的安全默认环境变量一起传给上游子进程。

## 命令行

```bash
cursor-mcp-response-proxy stdio [公共参数] [--env NAME=VALUE] -- COMMAND [ARGS...]
cursor-mcp-response-proxy sse [公共参数] --url URL [--header NAME=VALUE]
cursor-mcp-response-proxy streamable-http [公共参数] --url URL [--header NAME=VALUE]
```

HTTP 参数：

- `--header NAME=VALUE`：可重复，值支持 `${ENV_VAR}`。
- `--timeout`：常规 HTTP 操作超时，默认 120 秒。
- `--sse-read-timeout`：等待 SSE 新事件的超时，默认 300 秒。

公共环境变量：


| 变量                                                   | 说明        |
| ---------------------------------------------------- | --------- |
| `CURSOR_MCP_RESPONSE_PROXY_MAX_RESPONSE_CHARS`       | 响应保护阈值    |
| `CURSOR_MCP_RESPONSE_PROXY_PREVIEW_CHARS`            | 预览字符数     |
| `CURSOR_MCP_RESPONSE_PROXY_OUTPUT_DIR`               | 完整响应目录    |
| `CURSOR_MCP_RESPONSE_PROXY_TIMEOUT_SECONDS`          | HTTP 操作超时 |
| `CURSOR_MCP_RESPONSE_PROXY_SSE_READ_TIMEOUT_SECONDS` | SSE 读取超时  |


## 实现边界

- 三种上游传输由官方 MCP Python SDK 1.x 提供。
- 代理不创建业务级 `ClientSession`；控制消息、通知和服务端请求透明转发，超限的内容型响应按对应协议结构改写。
- 传输层不处理响应大小，响应处理层不发网络请求。
- 日志只写 stderr，stdout 只写单行 MCP JSON-RPC 消息。

## 目录

```text
src/cursor_mcp_response_proxy/
  __main__.py          # 命令入口
  config.py            # 子命令、请求头与环境变量配置
  proxy.py             # Cursor stdio 双向代理与请求关联
  transports.py        # stdio、SSE、Streamable HTTP 上游适配
  response_handler.py  # 体积判断与协议兼容改写
  storage.py           # 完整响应文件写入
tests/
  fixtures/            # 测试专用 MCP 上游
```

