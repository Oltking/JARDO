"""Coding-environment operator (owner scope, 2026-07-04): Jardo operates ONLY
within coding environments — editors (VS Code, Cursor, …), terminals, shells,
and coding agents. It does not drive general/non-coding apps.

Builds on the PTY terminal (core.computer_use.pty_terminal) for command
execution and the Security Sentinel (core.sentinel) for gating. macOS-first.
"""
