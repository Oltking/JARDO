"""Computer-use subsystem (spec §7): perception + control of the owner's machine.

macOS-first (§3). This package holds the perception/action pieces that live in
the Python core; synthetic input (enigo) lives in the Tauri shell (desktop/).
Every action is Sentinel-gated (§7.3) — nothing here executes ungated.
"""
