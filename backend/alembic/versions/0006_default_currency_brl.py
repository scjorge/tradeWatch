"""default currency BRL

A moeda padrão da plataforma passa a ser escolhida entre BRL (padrão) e dólar
(USDT). Contas existentes passam para BRL; quem preferir dólar escolhe em
Configurações. Resultados, posições e operações são refeitos na moeda nova na
próxima apuração (sincronização ou ao salvar a preferência).

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE users SET base_currency = 'BRL'")
    op.alter_column("users", "base_currency", existing_type=sa.String(length=16), server_default="BRL")


def downgrade() -> None:
    op.alter_column("users", "base_currency", existing_type=sa.String(length=16), server_default=None)
