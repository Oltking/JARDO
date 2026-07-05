"""Agent conductor (owner concept, 2026-07-05): Jardo runs CLI coding agents
(Claude Code, Gemini, …) on the owner's behalf — sets up the project folder,
reads its spec, launches the agent with the task, and auto-answers the agent's
permission prompts by safety + purpose.

Cross-platform by design: agents are driven through their CLIs (subprocess +
pathlib) and the permission hook, not OS-specific terminal automation, so this
works on macOS and Windows alike.
"""
