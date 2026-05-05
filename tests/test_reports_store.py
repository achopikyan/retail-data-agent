"""Saved Reports store: CRUD, ownership, GDPR cross-user delete."""
from __future__ import annotations

import pytest

from src.tools import reports_store


def test_save_and_list(tmp_db):
    rid = reports_store.save("alice", "Q4 Top Customers", "alice's report body")
    assert rid > 0
    reports = reports_store.list_for("alice")
    assert len(reports) == 1
    assert reports[0].title == "Q4 Top Customers"
    assert reports[0].owner_id == "alice"


def test_list_isolation_per_owner(tmp_db):
    reports_store.save("alice", "A1", "alice body")
    reports_store.save("bob", "B1", "bob body")
    assert len(reports_store.list_for("alice")) == 1
    assert len(reports_store.list_for("bob")) == 1
    assert len(reports_store.list_for(None)) == 2


def test_find_matching_substring_caseinsensitive(tmp_db):
    reports_store.save("alice", "Mentions Client X", "body about Client X")
    reports_store.save("alice", "Other report", "no client")
    matched = reports_store.find_matching("client x", owner_id="alice")
    assert len(matched) == 1
    assert "Client X" in matched[0].title


def test_owner_can_delete_own(tmp_db):
    rid = reports_store.save("alice", "A1", "body")
    deleted = reports_store.delete_ids([rid], actor_id="alice", actor_role="manager", reason="cleanup")
    assert deleted == 1
    assert reports_store.get(rid) is None


def test_manager_cannot_delete_others(tmp_db):
    bob_rid = reports_store.save("bob", "B1", "body")
    with pytest.raises(PermissionError):
        reports_store.delete_ids([bob_rid], actor_id="alice", actor_role="manager")


def test_gdpr_can_delete_across_users(tmp_db):
    a = reports_store.save("alice", "A1", "mentions Client X")
    b = reports_store.save("bob", "B1", "also mentions Client X")
    deleted = reports_store.delete_ids(
        [a, b], actor_id="legal", actor_role=reports_store.GDPR_ROLE, reason="GDPR request"
    )
    assert deleted == 2
    audit = reports_store.audit_recent()
    assert audit[0]["action"] == "delete_gdpr"


def test_audit_log_records_actions(tmp_db):
    rid = reports_store.save("alice", "A1", "body")
    reports_store.delete_ids([rid], actor_id="alice", actor_role="manager", reason="just because")
    audit = reports_store.audit_recent()
    assert audit[0]["actor_id"] == "alice"
    assert audit[0]["action"] == "delete"
    assert "just because" in (audit[0]["reason"] or "")
