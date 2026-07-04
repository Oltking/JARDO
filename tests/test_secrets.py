"""Keychain roundtrip (macOS only — core.secrets is macOS-first by design)."""

import sys
import uuid

import pytest

from core import secrets

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS Keychain only")

TEST_SERVICE = f"jarvis.test.{uuid.uuid4().hex[:8]}"


def test_write_read_delete_roundtrip():
    try:
        secrets.write_secret(TEST_SERVICE, "s3cret-value")
        assert secrets.read_secret(TEST_SERVICE) == "s3cret-value"
        # -U flag updates in place
        secrets.write_secret(TEST_SERVICE, "rotated")
        assert secrets.read_secret(TEST_SERVICE) == "rotated"
    finally:
        assert secrets.delete_secret(TEST_SERVICE) is True
    assert secrets.read_secret(TEST_SERVICE) is None


def test_read_missing_returns_none():
    assert secrets.read_secret("jarvis.test.does-not-exist") is None
