"""Contrato de módulos da plataforma.

Um módulo declara rotas, permissões, papéis padrão, itens de navegação e tarefas
periódicas. O núcleo apenas itera o registro: adicionar um módulo novo não exige
alterar o núcleo, só registrá-lo em ``app/modules/registry.py``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from fastapi import APIRouter
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class NavItem:
    label: str
    path: str
    icon: str
    permission: str | None = None
    order: int = 100


@dataclass(frozen=True)
class PeriodicTask:
    name: str
    interval_seconds: int
    run: Callable[[Session], None]


@dataclass
class ModuleSpec:
    key: str
    name: str
    description: str
    version: str = "1"
    core: bool = False  # módulos de núcleo não podem ser desativados
    routers: list[APIRouter] = field(default_factory=list)
    permissions: dict[str, str] = field(default_factory=dict)
    role_permissions: dict[str, list[str]] = field(default_factory=dict)
    nav: list[NavItem] = field(default_factory=list)
    periodic_tasks: list[PeriodicTask] = field(default_factory=list)
