"""user profile, session tokens, audit events

Revision ID: 666f2caba7b7
Revises: 34c70ede741a
Create Date: 2026-10-05 17:01:46.439692

"""
import secrets

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '666f2caba7b7'
down_revision = '34c70ede741a'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('audit_events',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('action', sa.String(length=40), nullable=False),
    sa.Column('actor_id', sa.Integer(), nullable=True),
    sa.Column('target_id', sa.Integer(), nullable=True),
    sa.Column('detail', sa.String(length=255), nullable=True),
    sa.Column('ip_address', sa.String(length=45), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['target_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('audit_events', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_audit_events_action'), ['action'], unique=False)
        batch_op.create_index(batch_op.f('ix_audit_events_created_at'), ['created_at'], unique=False)

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('full_name', sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column('email', sa.String(length=254), nullable=True))
        batch_op.add_column(sa.Column('must_change_password', sa.Boolean(), nullable=False,
                                      server_default=sa.false()))
        batch_op.add_column(sa.Column('session_token', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('created_by_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('password_changed_at', sa.DateTime(), nullable=True))
        batch_op.create_foreign_key('fk_users_created_by_id_users', 'users', ['created_by_id'], ['id'])

    # Existing users get their own session token (this signs them out once)
    conn = op.get_bind()
    for (user_id,) in conn.execute(sa.text("SELECT id FROM users")).fetchall():
        conn.execute(sa.text("UPDATE users SET session_token = :t WHERE id = :id"),
                     {"t": secrets.token_hex(16), "id": user_id})

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.alter_column('session_token', existing_type=sa.String(length=64), nullable=False)


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_constraint('fk_users_created_by_id_users', type_='foreignkey')
        batch_op.drop_column('password_changed_at')
        batch_op.drop_column('created_by_id')
        batch_op.drop_column('session_token')
        batch_op.drop_column('must_change_password')
        batch_op.drop_column('email')
        batch_op.drop_column('full_name')

    with op.batch_alter_table('audit_events', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_audit_events_created_at'))
        batch_op.drop_index(batch_op.f('ix_audit_events_action'))

    op.drop_table('audit_events')
