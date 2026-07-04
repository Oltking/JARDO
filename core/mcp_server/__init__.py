"""Jardo MCP server package (spec §4.3 — the Agent Supervisor exposed over MCP).

Other agents (Claude Code, Cursor, terminal agents) call this server's tools to
have Jardo review and gate their proposed actions through the Security Sentinel
(spec §6) before they execute. The server reuses core.sentinel.broker.Sentinel
verbatim — no supervision logic is reimplemented here.

NOTE ON THE `mcp/` NAME COLLISION: the real MCP Python SDK is imported as
`from mcp.server.fastmcp import FastMCP`. This package lives under `core/` (never
top-level `mcp/`) precisely so it can't shadow the SDK; the repo's top-level
`mcp/` deploy directory is only a namespace-package portion and is overridden by
the installed SDK's regular `mcp` package.
"""
