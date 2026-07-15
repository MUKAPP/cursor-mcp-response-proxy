# AGENTS.md

## 项目简介

面向 Cursor 的 MCP stdio 响应代理。Cursor 通过 stdio 启动代理，上游可使用 stdio、SSE 或 Streamable HTTP。当响应过大时，完整内容写入本地文件，并向 Cursor 返回预览和文件路径。

## 目录

- `src/cursor_mcp_response_proxy/`：代理实现
- `tests/`：单元测试
- `README.md`：安装、Cursor 配置与使用说明

## 常用命令

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
pip install pytest
PYTHONPATH=src pytest
python -m cursor_mcp_response_proxy --help
```

## 约定

- 用户可见文案、日志、错误信息使用中文
- 代码标识符使用英文
- 不要把 API Key 或令牌写入仓库；通过环境变量和 `--header NAME=${ENV_VAR}` 注入
- 过大响应默认写入 `~/.cache/cursor-mcp-response-proxy`
- 默认响应阈值为 10000 字符，修改前应考虑 Cursor 的工具结果大小限制

## 架构边界

- `transports.py`：只负责打开 stdio、SSE、Streamable HTTP 上游消息流
- `response_handler.py`：只负责体积判断、文件保存与协议兼容改写
- `proxy.py`：Cursor stdio 读写、双向转发与请求关联
- 不要在传输层处理响应大小，也不要在响应处理层发起网络请求
- 优先复用官方 MCP Python SDK 的传输实现，不自行复制协议状态机
