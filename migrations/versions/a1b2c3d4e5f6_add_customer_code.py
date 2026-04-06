"""Add customer_code, payment_type index, composite indexes

Revision ID: a1b2c3d4e5f6
Revises: e09949059341
Create Date: 2026-04-05 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = 'e09949059341'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('customers', schema=None) as batch_op:
        batch_op.add_column(sa.Column('customer_code', sa.String(length=50), nullable=True))
        batch_op.create_index(batch_op.f('ix_customers_customer_code'), ['customer_code'], unique=False)

    with op.batch_alter_table('payments', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_payments_payment_type'), ['payment_type'], unique=False)

    with op.batch_alter_table('invoices', schema=None) as batch_op:
        batch_op.create_index('ix_invoices_customer_status', ['customer_id', 'status'], unique=False)

    with op.batch_alter_table('route_stops', schema=None) as batch_op:
        batch_op.create_index('ix_route_stops_customer_completed', ['customer_id', 'completed'], unique=False)


def downgrade():
    with op.batch_alter_table('route_stops', schema=None) as batch_op:
        batch_op.drop_index('ix_route_stops_customer_completed')

    with op.batch_alter_table('invoices', schema=None) as batch_op:
        batch_op.drop_index('ix_invoices_customer_status')

    with op.batch_alter_table('payments', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_payments_payment_type'))

    with op.batch_alter_table('customers', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_customers_customer_code'))
        batch_op.drop_column('customer_code')
