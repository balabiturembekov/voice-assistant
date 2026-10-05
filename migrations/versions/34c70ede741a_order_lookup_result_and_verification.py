"""order lookup result and verification

Separates what Lisa found (lookup_result) and how the caller was verified
(verification) from the staff-managed status and notes.

Revision ID: 34c70ede741a
Revises: 8188b5c6049d
Create Date: 2026-10-05 16:43:36.859525

"""
import re

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '34c70ede741a'
down_revision = '8188b5c6049d'
branch_labels = None
depends_on = None

# Statuses the call flow used to write into orders.status
SYSTEM_STATUSES = {
    "found in afterbuy": "found",
    "overdue delivery": "found",
    "not found": "not_found",
}
VERIFICATION_LINE = re.compile(r"^Verification:.*$", re.MULTILINE)
# Lines the system used to append to staff notes (now shown on the call page)
SYSTEM_LINES = re.compile(
    r"^(Verification:|Voice message|External transcription|Order found:|Order not found in AfterBuy).*$",
    re.MULTILINE,
)


def _verification_from_events(steps):
    """Derive the verification result from the call's conversation events"""
    if ("verified", "phone") in steps:
        return "phone"
    if ("verified", "postal_code") in steps:
        return "postal_code"
    if ("not_verified", "postal_code_mismatch") in steps:
        return "failed"
    if ("not_verified", "no_phone_or_postal_code") in steps:
        return "not_possible"
    return None


def upgrade():
    with op.batch_alter_table('orders', schema=None) as batch_op:
        batch_op.add_column(sa.Column('lookup_result', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('verification', sa.String(length=20), nullable=True))

    conn = op.get_bind()
    orders = conn.execute(sa.text("SELECT id, call_id, status, notes FROM orders")).fetchall()
    for order_id, call_id, status, notes in orders:
        values = {}
        lookup = SYSTEM_STATUSES.get((status or "").strip().lower())
        if lookup:
            values["lookup_result"] = lookup
            values["status"] = None  # no staff status yet
        elif (status or "").strip().lower() == "in progress":
            values["status"] = None  # old default, never set by staff

        if notes and VERIFICATION_LINE.search(notes):
            steps = {
                (step, user_input)
                for step, user_input in conn.execute(
                    sa.text("SELECT step, user_input FROM conversations WHERE call_id = :id"),
                    {"id": call_id},
                )
            }
            values["verification"] = _verification_from_events(steps) or "pending"

        if notes and SYSTEM_LINES.search(notes):
            cleaned = re.sub(r"\n{3,}", "\n\n", SYSTEM_LINES.sub("", notes)).strip()
            values["notes"] = cleaned or None

        if values:
            assignments = ", ".join(f"{column} = :{column}" for column in values)
            conn.execute(
                sa.text(f"UPDATE orders SET {assignments} WHERE id = :id"),
                {**values, "id": order_id},
            )


def downgrade():
    with op.batch_alter_table('orders', schema=None) as batch_op:
        batch_op.drop_column('verification')
        batch_op.drop_column('lookup_result')
