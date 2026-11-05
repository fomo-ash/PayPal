"""capture_split check that also holds on SQLite's float NUMERIC

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("verdicts") as batch:
        batch.drop_constraint(op.f("ck_verdicts_capture_split"), type_="check")
        batch.create_check_constraint(op.f("ck_verdicts_capture_split"), "abs(capture - fee - worker_amount) < 0.005")


def downgrade() -> None:
    with op.batch_alter_table("verdicts") as batch:
        batch.drop_constraint(op.f("ck_verdicts_capture_split"), type_="check")
        batch.create_check_constraint(op.f("ck_verdicts_capture_split"), "capture = fee + worker_amount")
