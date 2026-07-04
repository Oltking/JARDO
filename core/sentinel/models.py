"""Sentinel data model (spec §4.3 Action Review + §6 pipeline).

Every action Jardo or a supervised sub-agent wants to execute is described as
an ActionRequest and judged into an ActionReview. No direct execution paths
(spec §0.3): executors must hold an approved review, never raw intent.
"""

from dataclasses import dataclass, field
from enum import StrEnum


class Verdict(StrEnum):
    APPROVE = "approve"
    APPROVE_WITH_EDITS = "approve-with-edits"
    DENY = "deny"
    ESCALATE = "escalate-to-owner"


class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Tier(StrEnum):
    """Permission Broker tiers (spec §6.5)."""

    ALWAYS_ALLOW = "always-allow"
    ASK_ONCE = "ask-once"
    ALWAYS_ASK = "always-ask"


@dataclass
class ActionRequest:
    actor: str            # "core" | "worker" | agent id (Phase 4: "claude-code", ...)
    action_type: str      # e.g. "shell.run", "net.fetch", "fs.write", "app.open"
    target: str           # command line, URL, path, app name
    stated_goal: str      # what the actor claims this achieves (necessity test input)
    payload: dict = field(default_factory=dict)


@dataclass
class Finding:
    check: str
    severity: Severity
    message: str


@dataclass
class ActionReview:
    """Structured review, one per proposed action (spec §4.3)."""

    request: ActionRequest          # 1. what the agent wants to do (verbatim)
    expected_outcome: str           # 2. expected outcome
    findings: list[Finding]         # 3. disadvantages / risks
    necessary: bool                 # 4. necessity test result
    necessity_reason: str
    verdict: Verdict                # 5. verdict
    severity: Severity              # max of findings (drives §6.6 reporting)
    tier: Tier                      # broker tier that applied
