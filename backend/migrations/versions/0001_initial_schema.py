"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-11-05 00:48:34.683044
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:

    op.create_table(
        "paypal_events",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("type", sa.String(length=80), nullable=False),
        sa.Column("resource_id", sa.String(length=64), nullable=True),
        sa.Column(
            "raw",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("verified", sa.Boolean(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_paypal_events")),
    )
    with op.batch_alter_table("paypal_events", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_paypal_events_resource_id"), ["resource_id"], unique=False
        )

    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("paypal_payer_id", sa.String(length=32), nullable=True),
        sa.Column("email", sa.String(length=254), nullable=True),
        sa.Column("display_name", sa.String(length=80), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("role IN ('buyer','worker','admin')", name=op.f("ck_users_role")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("paypal_payer_id", name=op.f("uq_users_paypal_payer_id")),
    )
    op.create_table(
        "agents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("api_key_hash", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["owner_user_id"], ["users.id"], name=op.f("fk_agents_owner_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agents")),
        sa.UniqueConstraint("api_key_hash", name=op.f("uq_agents_api_key_hash")),
    )
    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("buyer_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("spec_md", sa.Text(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("min_score", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column("fee_bps", sa.Integer(), nullable=False),
        sa.Column("deadline_hours", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("suite_sha256", sa.String(length=64), nullable=True),
        sa.Column("paypal_order_id", sa.String(length=64), nullable=True),
        sa.Column("authorization_id", sa.String(length=64), nullable=True),
        sa.Column("authorized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("honor_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("capture_id", sa.String(length=64), nullable=True),
        sa.Column("payout_batch_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("amount > 0", name=op.f("ck_jobs_amount_positive")),
        sa.CheckConstraint("fee_bps >= 0 AND fee_bps <= 10000", name=op.f("ck_jobs_fee_range")),
        sa.CheckConstraint(
            "min_score >= 0 AND min_score <= 1", name=op.f("ck_jobs_min_score_range")
        ),
        sa.ForeignKeyConstraint(["buyer_id"], ["users.id"], name=op.f("fk_jobs_buyer_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jobs")),
        sa.UniqueConstraint("authorization_id", name=op.f("uq_jobs_authorization_id")),
    )
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_jobs_state"), ["state"], unique=False)

    op.create_table(
        "audit_log",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("event", sa.String(length=60), nullable=False),
        sa.Column(
            "payload",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("prev_hash", sa.String(length=64), nullable=False),
        sa.Column("hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], name=op.f("fk_audit_log_job_id_jobs")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_log")),
        sa.UniqueConstraint("job_id", "seq", name="job_seq"),
    )
    with op.batch_alter_table("audit_log", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_audit_log_job_id"), ["job_id"], unique=False)

    op.create_table(
        "claims",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("worker_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.ForeignKeyConstraint(
            ["agent_id"], ["agents.id"], name=op.f("fk_claims_agent_id_agents")
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], name=op.f("fk_claims_job_id_jobs")),
        sa.ForeignKeyConstraint(
            ["worker_id"], ["users.id"], name=op.f("fk_claims_worker_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_claims")),
    )
    with op.batch_alter_table("claims", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_claims_job_id"), ["job_id"], unique=False)

    op.create_table(
        "ledger_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("account", sa.String(length=30), nullable=False),
        sa.Column("debit", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("credit", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("ref", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("(debit = 0) OR (credit = 0)", name=op.f("ck_ledger_entries_one_side")),
        sa.CheckConstraint(
            "debit >= 0 AND credit >= 0", name=op.f("ck_ledger_entries_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["jobs.id"], name=op.f("fk_ledger_entries_job_id_jobs")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ledger_entries")),
    )
    with op.batch_alter_table("ledger_entries", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_ledger_entries_job_id"), ["job_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_ledger_entries_ref"), ["ref"], unique=False)

    op.create_table(
        "outbox",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("idempotency_key", sa.String(length=120), nullable=False),
        sa.Column(
            "payload",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "response",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('pending','done','failed')", name=op.f("ck_outbox_status")),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], name=op.f("fk_outbox_job_id_jobs")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_outbox")),
        sa.UniqueConstraint("idempotency_key", name=op.f("uq_outbox_idempotency_key")),
    )
    with op.batch_alter_table("outbox", schema=None) as batch_op:
        batch_op.create_index("ix_outbox_due", ["status", "next_attempt_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_outbox_job_id"), ["job_id"], unique=False)

    op.create_table(
        "receipts",
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("json_key", sa.String(length=300), nullable=False),
        sa.Column("pdf_key", sa.String(length=300), nullable=True),
        sa.Column("signature", sa.Text(), nullable=False),
        sa.Column("public_key_id", sa.String(length=40), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], name=op.f("fk_receipts_job_id_jobs")),
        sa.PrimaryKeyConstraint("job_id", name=op.f("pk_receipts")),
    )
    op.create_table(
        "spec_checks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("test_id", sa.String(length=80), nullable=False),
        sa.Column("implied", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], name=op.f("fk_spec_checks_job_id_jobs")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_spec_checks")),
    )
    with op.batch_alter_table("spec_checks", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_spec_checks_job_id"), ["job_id"], unique=False)

    op.create_table(
        "suites",
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("r2_key", sa.String(length=300), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("reference_key", sa.String(length=300), nullable=False),
        sa.Column("generator_key", sa.String(length=300), nullable=True),
        sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], name=op.f("fk_suites_job_id_jobs")),
        sa.PrimaryKeyConstraint("job_id", name=op.f("pk_suites")),
    )
    op.create_table(
        "test_groups",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=40), nullable=False),
        sa.Column("weight", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column("n_tests", sa.Integer(), nullable=False),
        sa.Column("fresh_count", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], name=op.f("fk_test_groups_job_id_jobs")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_test_groups")),
        sa.UniqueConstraint("job_id", "name", name="job_group"),
    )
    with op.batch_alter_table("test_groups", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_test_groups_job_id"), ["job_id"], unique=False)

    op.create_table(
        "submissions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("worker_id", sa.Uuid(), nullable=False),
        sa.Column("r2_key", sa.String(length=300), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("grading_seed", sa.String(length=20), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["claim_id"], ["claims.id"], name=op.f("fk_submissions_claim_id_claims")
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], name=op.f("fk_submissions_job_id_jobs")),
        sa.ForeignKeyConstraint(
            ["worker_id"], ["users.id"], name=op.f("fk_submissions_worker_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_submissions")),
        sa.UniqueConstraint("job_id", "worker_id", name="one_per_worker"),
    )
    with op.batch_alter_table("submissions", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_submissions_job_id"), ["job_id"], unique=False)

    op.create_table(
        "ai_reviews",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("submission_id", sa.Uuid(), nullable=False),
        sa.Column("model", sa.String(length=80), nullable=False),
        sa.Column("decision", sa.String(length=20), nullable=False),
        sa.Column(
            "findings",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("langfuse_trace_id", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["submission_id"],
            ["submissions.id"],
            name=op.f("fk_ai_reviews_submission_id_submissions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_reviews")),
    )
    with op.batch_alter_table("ai_reviews", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_ai_reviews_submission_id"), ["submission_id"], unique=False
        )

    op.create_table(
        "runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("submission_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("group_name", sa.String(length=40), nullable=False),
        sa.Column("passed", sa.Integer(), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column(
            "flaky_ids",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "details",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["submission_id"], ["submissions.id"], name=op.f("fk_runs_submission_id_submissions")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_runs")),
    )
    with op.batch_alter_table("runs", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_runs_submission_id"), ["submission_id"], unique=False)

    op.create_table(
        "scan_findings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("submission_id", sa.Uuid(), nullable=False),
        sa.Column("rule", sa.String(length=60), nullable=False),
        sa.Column("file", sa.String(length=300), nullable=False),
        sa.Column("line", sa.Integer(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("hard_signal", sa.String(length=40), nullable=True),
        sa.ForeignKeyConstraint(
            ["submission_id"],
            ["submissions.id"],
            name=op.f("fk_scan_findings_submission_id_submissions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scan_findings")),
    )
    with op.batch_alter_table("scan_findings", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_scan_findings_submission_id"), ["submission_id"], unique=False
        )

    op.create_table(
        "verdicts",
        sa.Column("submission_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("raw_score", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column("score", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column("capture", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("fee", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("worker_amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("released", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("settlement", sa.String(length=14), nullable=False),
        sa.Column("policy_reason", sa.Text(), nullable=False),
        sa.Column("decided_by", sa.String(length=10), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("capture = fee + worker_amount", name=op.f("ck_verdicts_capture_split")),
        sa.CheckConstraint(
            "capture >= 0 AND fee >= 0 AND worker_amount >= 0 AND released >= 0",
            name=op.f("ck_verdicts_money_non_negative"),
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], name=op.f("fk_verdicts_job_id_jobs")),
        sa.ForeignKeyConstraint(
            ["submission_id"],
            ["submissions.id"],
            name=op.f("fk_verdicts_submission_id_submissions"),
        ),
        sa.PrimaryKeyConstraint("submission_id", name=op.f("pk_verdicts")),
        sa.UniqueConstraint("job_id", name=op.f("uq_verdicts_job_id")),
    )


def downgrade() -> None:

    op.drop_table("verdicts")
    with op.batch_alter_table("scan_findings", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_scan_findings_submission_id"))

    op.drop_table("scan_findings")
    with op.batch_alter_table("runs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_runs_submission_id"))

    op.drop_table("runs")
    with op.batch_alter_table("ai_reviews", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_ai_reviews_submission_id"))

    op.drop_table("ai_reviews")
    with op.batch_alter_table("submissions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_submissions_job_id"))

    op.drop_table("submissions")
    with op.batch_alter_table("test_groups", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_test_groups_job_id"))

    op.drop_table("test_groups")
    op.drop_table("suites")
    with op.batch_alter_table("spec_checks", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_spec_checks_job_id"))

    op.drop_table("spec_checks")
    op.drop_table("receipts")
    with op.batch_alter_table("outbox", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_outbox_job_id"))
        batch_op.drop_index("ix_outbox_due")

    op.drop_table("outbox")
    with op.batch_alter_table("ledger_entries", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_ledger_entries_ref"))
        batch_op.drop_index(batch_op.f("ix_ledger_entries_job_id"))

    op.drop_table("ledger_entries")
    with op.batch_alter_table("claims", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_claims_job_id"))

    op.drop_table("claims")
    with op.batch_alter_table("audit_log", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_audit_log_job_id"))

    op.drop_table("audit_log")
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_jobs_state"))

    op.drop_table("jobs")
    op.drop_table("agents")
    op.drop_table("users")
    with op.batch_alter_table("paypal_events", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_paypal_events_resource_id"))

    op.drop_table("paypal_events")
