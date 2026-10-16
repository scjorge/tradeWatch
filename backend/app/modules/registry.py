"""Registro de módulos. Novos módulos são adicionados aqui sem alterar o núcleo."""

from __future__ import annotations

from app.core.modules import ModuleSpec, NavItem, PeriodicTask
from app.modules.admin.router import router as admin_router
from app.modules.auth.router import router as auth_router
from app.modules.notifications.router import router as notifications_router
from app.modules.notifications.service import deliver_pending
from app.modules.trades import tasks as trade_tasks
from app.modules.trades.router_connections import router as connections_router
from app.modules.trades.router_cycles import router as cycles_router
from app.modules.trades.router_data import dashboard, portfolio
from app.modules.trades.router_data import router as trades_router
from app.modules.users.router import router as me_router

CORE = ModuleSpec(
    key="core",
    name="Núcleo",
    description="Autenticação, usuários, preferências, auditoria e administração.",
    core=True,
    routers=[auth_router, me_router, admin_router],
    permissions={
        "admin:users": "Administrar usuários",
        "admin:modules": "Administrar módulos",
        "admin:audit": "Consultar auditoria",
        "admin:metrics": "Consultar métricas operacionais",
    },
    role_permissions={"admin": ["admin:users", "admin:modules", "admin:audit", "admin:metrics"]},
    nav=[
        NavItem("Configurações", "/settings", "settings", order=90),
        NavItem("Administração", "/admin", "shield", permission="admin:users", order=95),
    ],
)

TRADES = ModuleSpec(
    key="trades",
    name="Trades",
    description="Conexões com corretoras, sincronização, operações, posições, resultados e patrimônio.",
    routers=[connections_router, cycles_router, trades_router, portfolio, dashboard],
    permissions={"trades:read": "Consultar os próprios dados de trades", "integrations:manage": "Gerenciar as próprias integrações"},
    role_permissions={"user": ["trades:read", "integrations:manage"], "admin": ["trades:read", "integrations:manage"]},
    nav=[
        NavItem("Visão geral", "/", "dashboard", permission="trades:read", order=10),
        NavItem("Trades", "/trades", "chart", permission="trades:read", order=20),
        NavItem("Operações", "/operations", "list", permission="trades:read", order=30),
        NavItem("Carteiras e saldos", "/portfolio", "wallet", permission="trades:read", order=40),
        NavItem("Relatórios", "/reports", "report", permission="trades:read", order=50),
        NavItem("Integrações", "/integrations", "plug", permission="integrations:manage", order=60),
    ],
    periodic_tasks=[
        PeriodicTask("schedule_syncs", 60, trade_tasks.schedule_periodic_syncs),
        PeriodicTask("daily_summaries", 300, trade_tasks.daily_summaries),
        PeriodicTask("equity_alerts", 900, trade_tasks.equity_alerts),
        PeriodicTask("open_position_prices", 300, trade_tasks.refresh_open_prices),
    ],
)

NOTIFICATIONS = ModuleSpec(
    key="notifications",
    name="Notificações",
    description="Canais (Telegram) e preferências de notificação.",
    routers=[notifications_router],
    permissions={"notifications:manage": "Gerenciar as próprias notificações"},
    role_permissions={"user": ["notifications:manage"], "admin": ["notifications:manage"]},
    nav=[NavItem("Notificações", "/notifications", "bell", permission="notifications:manage", order=70)],
    periodic_tasks=[PeriodicTask("deliver_notifications", 10, lambda db: deliver_pending(db))],
)

REGISTRY: list[ModuleSpec] = [CORE, TRADES, NOTIFICATIONS]
