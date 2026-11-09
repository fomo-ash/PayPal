"""Postgres blob store and host-style database URLs."""

import pytest
from test_e2e_api import grade_and_settle
from test_money_worker import mock_capture_and_payout

from verdict.config import Settings
from verdict.db.session import normalize_url
from verdict.storage import DbBlobStore, LocalBlobStore, make_store


def test_db_store_round_trip_and_overwrite(Session):
    store = DbBlobStore(Session)
    store.put("suites/a/b.json", b"one")
    store.put("suites/a/b.json", b"two")
    assert store.get("suites/a/b.json") == b"two"
    with pytest.raises(FileNotFoundError):
        store.get("suites/a/missing.json")
    with pytest.raises(ValueError):
        store.put("../escape", b"x")


def test_whole_flow_runs_on_the_db_store(api, submitted, pp, Session):
    api.services.store = DbBlobStore(Session)
    buyer, _, job_id, sub_id = submitted("honest_full")
    mock_capture_and_payout(pp)
    grade_and_settle(api, sub_id)
    view = api.get(f"/submissions/{sub_id}", headers=buyer).json()
    assert view["job_state"] == "PAID" and view["verdict"]["capture"] == "100.00"
    code = api.get(f"/submissions/{sub_id}/code", headers=buyer).json()
    assert "def solve" in code["files"]["solution.py"]


def test_make_store_picks_the_backend(Session, tmp_path):
    assert isinstance(make_store(Settings(_env_file=None, blob_backend="db"), Session), DbBlobStore)
    local = make_store(Settings(_env_file=None, blob_dir=str(tmp_path)), Session)
    assert isinstance(local, LocalBlobStore)
    with pytest.raises(ValueError):
        make_store(Settings(_env_file=None, blob_backend="s3"), Session)


@pytest.mark.parametrize("raw, want", [
    ("postgres://u:p@h:5432/db", "postgresql+psycopg://u:p@h:5432/db"),
    ("postgresql://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
    ("postgresql+psycopg://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
    ("sqlite:///data/v.db", "sqlite:///data/v.db"),
])
def test_host_database_urls_use_psycopg3(raw, want):
    assert normalize_url(raw) == want
