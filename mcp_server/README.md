# MCP server for Claude Desktop

Lets Claude call the backend as tools (`lookup_domain` and `health`). Start the backend first, then add this
to Claude Desktop's `claude_desktop_config.json` with your own absolute paths (on Windows the Python is
`.venv\Scripts\python.exe`), and fully restart Claude Desktop:

```json
{"mcpServers": {"ioc-dns": {
  "command": "/path/to/ioc-simple-dns/.venv/bin/python",
  "args": ["/path/to/ioc-simple-dns/mcp_server/server.py"],
  "env": {"BACKEND_URL": "<the address the backend prints>"}}}}
```

`BACKEND_URL` is required (there is no default). If your file already has other servers, add `"ioc-dns"` inside
the existing `"mcpServers"` object. If the server shows as failed, open its log under "View logs" in Claude Desktop's settings.
