"""Autonomous work (spec §4.2, §8): Jardo pursues the owner's objective while
they are away. When a command/agent request comes up, Jardo checks its PURPOSE
against the objective and its SAFETY, then acts on the owner's behalf — it does
not queue and wait. Only genuinely unsafe or off-task actions are refused.
"""
