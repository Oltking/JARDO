"""Thin MCP client helper (spec §4.3: JARVIS also acts as an MCP client to read
other agents' plans / tool catalogs).

Connects to an external MCP server over stdio and lists its tools, per
  docs/vendor/mcp/quickstart-build-client.md
  (`from mcp import ClientSession, StdioServerParameters`,
   `from mcp.client.stdio import stdio_client`, `session.list_tools()`).

This is deliberately minimal — enough to discover what a subordinate agent's
server exposes so the Supervisor knows what it might be asked to gate.
"""

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def list_server_tools(command: str, args: list[str] | None = None,
                            env: dict[str, str] | None = None) -> list[dict]:
    """Launch an external MCP server via `command args` over stdio, initialize
    the session, and return its advertised tools as plain dicts
    (name/description/input schema). The subprocess is torn down on return.
    """
    params = StdioServerParameters(command=command, args=args or [], env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            response = await session.list_tools()
            return [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.inputSchema,
                }
                for tool in response.tools
            ]
