"""intervalo de atualização automática de cotações

Preferência do usuário (Configurações): de quantos em quantos segundos a tela de
Operações atualiza as cotações sozinha. 0 desliga.

Revision ID: 0007
Revises: 0006
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("price_refresh_seconds", sa.Integer(), nullable=False, server_default="60"))


def downgrade() -> None:
    op.drop_column("users", "price_refresh_seconds")
