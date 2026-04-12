import pytest
from research_team.security.audit_log import AuditLog


def test_record_and_read_entries(tmp_path):
    log = AuditLog(tmp_path / "audit.log")
    log.record("query_sanitized", {"query": "climate change"})
    entries = log.entries()
    assert len(entries) == 1
    assert entries[0]["event"] == "query_sanitized"
    assert entries[0]["query"] == "climate change"
    assert "timestamp" in entries[0]


def test_multiple_entries_appended(tmp_path):
    log = AuditLog(tmp_path / "audit.log")
    log.record("event_a", {"x": 1})
    log.record("event_b", {"x": 2})
    entries = log.entries()
    assert len(entries) == 2
    assert entries[0]["event"] == "event_a"
    assert entries[1]["event"] == "event_b"


def test_entries_empty_when_log_missing(tmp_path):
    log = AuditLog(tmp_path / "nonexistent.log")
    assert log.entries() == []


def test_log_file_created_on_record(tmp_path):
    log_path = tmp_path / "subdir" / "audit.log"
    log = AuditLog(log_path)
    log.record("test_event", {})
    assert log_path.exists()
