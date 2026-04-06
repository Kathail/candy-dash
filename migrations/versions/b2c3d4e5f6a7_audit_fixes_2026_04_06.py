"""Add paid_by_payment_id to invoices, invoice_date indexes

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-04-06 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b2c3d4e5f6a7'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('invoices', schema=None) as batch_op:
        batch_op.add_column(sa.Column('paid_by_payment_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_invoices_paid_by_payment_id', 'payments',
            ['paid_by_payment_id'], ['id']
        )
        batch_op.create_index('ix_invoices_date', ['invoice_date'], unique=False)
        batch_op.create_index('ix_invoices_date_customer', ['invoice_date', 'customer_id'], unique=False)


def downgrade():
    with op.batch_alter_table('invoices', schema=None) as batch_op:
        batch_op.drop_index('ix_invoices_date_customer')
        batch_op.drop_index('ix_invoices_date')
        batch_op.drop_constraint('fk_invoices_paid_by_payment_id', type_='foreignkey')
        batch_op.drop_column('paid_by_payment_id')
