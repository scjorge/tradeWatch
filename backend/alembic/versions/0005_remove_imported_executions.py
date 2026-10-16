"""remove imported executions

A importação de arquivos foi retirada: o sistema usa somente dados da corretora.
Apaga execuções importadas (source <> 'api') e, em cascata, ciclos e resultados
derivados delas. As posições dos usuários afetados são refeitas na próxima apuração.

Revision ID: 0005
Revises: 0004
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DELETE FROM positions WHERE user_id IN (SELECT DISTINCT user_id FROM trade_executions WHERE source <> 'api')")
    op.execute("DELETE FROM trade_executions WHERE source <> 'api'")


def downgrade() -> None:
    pass  # dados importados não podem ser restaurados
