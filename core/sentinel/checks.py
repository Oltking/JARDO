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
# A denylist can never be complete, so autonomous approval ALSO requires the
# command to be on the safe allowlist below (is_recognizably_safe) — this list
# is the second line, catching dangerous *flags* on otherwise-allowlisted tools.
_DANGEROUS = [
    (re.compile(r"rm\s+-[a-z]*r[a-z]*\s+[/~]|rm\s+-[a-z]*f[a-z]*\s+[/~]"), Severity.CRITICAL, "recursive delete at root/home"),
    (re.compile(r"\brm\s+-[a-z]*r"), Severity.MEDIUM, "recursive delete"),
    (re.compile(r"\bfind\b[^\n]*-(delete|exec|execdir)\b"), Severity.HIGH, "find with delete/exec"),
    (re.compile(r"\bgit\s+clean\s+-[a-z]*[fd]"), Severity.MEDIUM, "git clean (removes untracked files)"),
    (re.compile(r"\b(shred|truncate)\b"), Severity.HIGH, "file destruction"),
    (re.compile(r"\bdd\s+if=.*of=/dev/|>\s*/dev/(sd|disk|nvme|hd)"), Severity.CRITICAL, "raw disk write"),
    (re.compile(r"mkfs\.|diskutil\s+erase", re.I), Severity.CRITICAL, "filesystem format"),
    (re.compile(r"\(\s*\)\s*\{[^}]*:\s*\|\s*:"), Severity.HIGH, "fork bomb"),
    (re.compile(r"curl[^|;\n]*\|\s*(ba|z|k)?sh|wget[^|;\n]*\|\s*(ba|z|k)?sh"), Severity.HIGH, "pipe remote script to shell"),
    (re.compile(r"\b(python3?|perl|ruby|php|node|deno|osascript)\b[^\n]*\s-(c|e)\b"), Severity.MEDIUM, "inline code execution"),
    (re.compile(r"\beval\s*\(|\bexec\s*\(|\beval\s+[\"'$]"), Severity.HIGH, "dynamic code evaluation"),
    (re.compile(r"\bsudo\b|\bchmod\s+(-[a-zA-Z]*R[a-zA-Z]*\s+)?[0-7]*7[0-7]{2}\b|\bchmod\s+-[a-zA-Z]*R"), Severity.MEDIUM, "privilege escalation / recursive perms"),
    (re.compile(r"/etc/(passwd|shadow|sudoers)|~/.ssh/|id_rsa|\.aws/credentials|\.env\b"), Severity.HIGH, "credential or system file access"),
    (re.compile(r"\bDROP\s+(TABLE|DATABASE)\b|\bTRUNCATE\b", re.I), Severity.HIGH, "destructive SQL"),
    (re.compile(r"git\s+push\s+[^\n]*--force|git\s+reset\s+--hard\s+origin"), Severity.MEDIUM, "history-destructive git"),
    (re.compile(r"\bnmap\b|\bmasscan\b|\bsqlmap\b|\bhydra\b|\bnikto\b", re.I), Severity.CRITICAL, "active scanning tool (forbidden, SECURITY.md rule 2)"),
]

# Allowlist for UNATTENDED auto-approval (audit #1): a command is auto-approvable
# only if every segment's leading program is a recognized dev/read-only tool.
# Anything else is declined (not run) when Jardo acts on its own — a denylist
# alone is unsafe. Dangerous *flags* on these tools are still caught above.
_SAFE_PROGRAMS = frozenset("""
ls pwd cd echo printf cat head tail less more wc grep rg egrep fgrep ag sort uniq
cut awk sed tr column jq yq diff comm file stat tree which type command env
printenv date whoami hostname uname df du ps sleep true clear open
git gh
node npm pnpm yarn npx bun deno tsc vite next eslint prettier jest vitest
python python3 pip pip3 uv uvx pipx pytest ruff black mypy isort flake8 pylint
tox poetry pipenv hatch alembic uvicorn
cargo rustc rustup rustfmt clippy go gofmt godoc
make cmake ninja meson gradle mvn dotnet
mkdir touch cp mv ln readlink realpath basename dirname
curl wget rsync scp
brew
docker
tsc bundle rake ruby gem php composer swift xcodebuild
""".split())


def is_recognizably_safe(command: str, extra_allowed: frozenset = frozenset()) -> bool:
    """True only if every && / || / | / ; segment starts with a recognized safe
    program. Keeps unattended auto-approval conservative: unknown commands are
    declined, never run (audit #1). `extra_allowed` is the owner's personal
    learned allowlist (programs they've said to always allow)."""
    if not command or not command.strip():
        return False
    allowed = _SAFE_PROGRAMS | extra_allowed
    for segment in re.split(r"&&|\|\||\||;|\n", command):
        toks = segment.strip().split()
        # Skip leading VAR=value assignments.
        i = 0
        while i < len(toks) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", toks[i]):
            i += 1
        if i >= len(toks):
            continue  # empty segment (e.g. trailing operator)
        program = toks[i].rsplit("/", 1)[-1]  # basename of ./bin/tool
        if program not in allowed:
            return False
    return True

_SECRET_PATTERNS = [
    (re.compile(r"(sk|pk|api|key|token|secret)[-_][A-Za-z0-9_-]{16,}", re.I), "credential-shaped string"),
    (re.compile(r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----"), "private key material"),
]

_PLAINTEXT_HTTP = re.compile(r"\bhttp://(?!127\.0\.0\.1|localhost)", re.I)


def redact(text: str) -> str:
    """Mask credential-shaped substrings before persisting to the audit log
    (SECURITY.md — never store secrets, even in logs)."""
    if not text:
        return text
    for pattern, _label in _SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


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
