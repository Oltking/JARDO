"""Runnable entrypoint: `python -m core.mcp_server` starts the stdio server.

See core/mcp_server/server.py for the tool definitions and doc citations.
"""

from core.mcp_server.server import main

if __name__ == "__main__":
    main()
