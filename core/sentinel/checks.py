"""Static checks (spec §6.1–§6.3). All checks are PASSIVE.

LEGAL BOUNDARY (SECURITY.md rule 2, spec §6.3): nothing in this module may probe,
scan, fuzz, or otherwise actively test a third-party system. Network checks are
limited to properties of connections Jardo was already asked to make (scheme,
TLS validity) and locally computable inspection of code/text. Active scanning of
systems the owner does not own is illegal without written authorization.
"""

import re

from core.sentinel.models import ActionRequest, Finding, Severity

# Dangerous shell / code patterns (§6.1). Each entry: (pattern, severity, label).
_DANGEROUS = [
    (re.compile(r"rm\s+-rf?\s+[/~]|rm\s+-fr?\s+[/~]"), Severity.CRITICAL, "recursive delete at root/home"),
    (re.compile(r"\bdd\s+if=.*of=/dev/"), Severity.CRITICAL, "raw disk write"),
    (re.compile(r"mkfs\.|diskutil\s+erase", re.I), Severity.CRITICAL, "filesystem format"),
    (re.compile(r"curl[^|;\n]*\|\s*(ba)?sh|wget[^|;\n]*\|\s*(ba)?sh"), Severity.HIGH, "pipe remote script to shell"),
    (re.compile(r"\beval\s*\(|\bexec\s*\("), Severity.HIGH, "dynamic code evaluation"),
    (re.compile(r"\bsudo\b|\bchmod\s+777\b"), Severity.MEDIUM, "privilege escalation / world-writable"),
    (re.compile(r"/etc/(passwd|shadow|sudoers)|~/.ssh/|id_rsa|\.aws/credentials|\.env\b"), Severity.HIGH, "credential or system file access"),
    (re.compile(r"\bDROP\s+(TABLE|DATABASE)\b|\bTRUNCATE\b", re.I), Severity.HIGH, "destructive SQL"),
    (re.compile(r"git\s+push\s+.*--force|git\s+reset\s+--hard\s+origin"), Severity.MEDIUM, "history-destructive git"),
    (re.compile(r"\bnmap\b|\bmasscan\b|\bsqlmap\b|\bhydra\b|\bnikto\b", re.I), Severity.CRITICAL, "active scanning tool (forbidden, SECURITY.md rule 2)"),
]

_SECRET_PATTERNS = [
    (re.compile(r"(sk|pk|api|key|token|secret)[-_][A-Za-z0-9_-]{16,}", re.I), "credential-shaped string"),
    (re.compile(r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----"), "private key material"),
]

_PLAINTEXT_HTTP = re.compile(r"\bhttp://(?!127\.0\.0\.1|localhost)", re.I)


def scan_dangerous_patterns(request: ActionRequest) -> list[Finding]:
    text = f"{request.target}\n{request.payload}"
    findings = []
    for pattern, severity, label in _DANGEROUS:
        if pattern.search(text):
            findings.append(Finding("dangerous-pattern", severity, label))
    return findings


def scan_secrets(request: ActionRequest) -> list[Finding]:
    text = f"{request.target}\n{request.payload}"
    return [
        Finding("secret-exposure", Severity.HIGH, f"{label} present in action payload")
        for pattern, label in _SECRET_PATTERNS if pattern.search(text)
    ]


def check_transport(request: ActionRequest) -> list[Finding]:
    """Passive transport check (§6.1): flag plaintext HTTP to non-local hosts."""
    if request.action_type.startswith("net.") and _PLAINTEXT_HTTP.search(request.target):
        return [Finding("transport", Severity.MEDIUM, "plaintext http:// to remote host")]
    return []


_STOPWORDS = frozenset(
    "the a an and or to of for in on with my our your this that is are be will "
    "please can could would want need it its from at by as do does".split()
)


def necessity_test(request: ActionRequest) -> tuple[bool, str]:
    """Permission minimization (§6.2/§4.3.4): is the action plausibly required
    for the stated goal? MVP heuristic: meaningful-word overlap between goal and
    action; Phase 4 upgrades this to a model judgment for agent-proposed actions."""
    def words(text: str) -> set[str]:
        return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in _STOPWORDS}

    goal_words = words(request.stated_goal)
    action_words = words(f"{request.action_type} {request.target}")
    if not goal_words:
        return False, "no stated goal — cannot justify action"
    overlap = goal_words & action_words
    if overlap:
        return True, f"goal/action overlap: {sorted(overlap)[:5]}"
    return False, "action shares nothing with the stated goal"
