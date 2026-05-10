"""Add compound index on purchases(supplier, purchase_date)

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-04-20 21:00:00.000000

"""
from alembic import op


revision = 'c3d4e5f6a7b8'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('purchases', schema=None) as batch_op:
        batch_op.create_index('ix_purchases_supplier_date', ['supplier', 'purchase_date'], unique=False)


def downgrade():
    with op.batch_alter_table('purchases', schema=None) as batch_op:
        batch_op.drop_index('ix_purchases_supplier_date')
