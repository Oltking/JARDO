"""The personal learned allowlist lets the owner approve a legit-but-unusual
command once, so the conservative gate stops declining it — without loosening
the defaults for everyone else."""

from core.sentinel.checks import is_recognizably_safe


def test_unknown_program_declined_by_default():
    assert is_recognizably_safe("./scripts/deploy.sh --prod") is False


def test_learned_allowlist_permits_it():
    allowed = frozenset({"deploy.sh"})
    assert is_recognizably_safe("./scripts/deploy.sh --prod", allowed) is True


def test_learned_allowlist_does_not_bypass_the_danger_scan():
    # is_recognizably_safe only vets the *program*; a dangerous command must still
    # be caught by scan_dangerous_patterns in the decider. Here we prove the
    # allowlist alone doesn't make "rm" safe as a program name.
    assert is_recognizably_safe("rm -rf /", frozenset({"rm"})) is True  # program ok...
    from core.sentinel.checks import scan_dangerous_patterns
    from core.sentinel.models import ActionRequest, Severity
    findings = scan_dangerous_patterns(ActionRequest("a", "shell.run", "rm -rf /", ""))
    # ...but the scan still flags it, so the decider blocks it regardless.
    assert any(f.severity == Severity.CRITICAL for f in findings)


def test_defaults_unchanged_when_no_allowlist():
    assert is_recognizably_safe("pytest -q") is True
    assert is_recognizably_safe("weirdtool --go") is False
