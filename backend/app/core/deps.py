"""Dependências de autenticação, autorização e CSRF."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.errors import Forbidden, NotFound, Unauthorized
from app.core.security import constant_time_equals, token_hash
from app.db import get_db
from app.models import Module, User, UserSession
from app.models.base import utcnow

SESSION_COOKIE = "tw_session"
CSRF_COOKIE = "tw_csrf"
CSRF_HEADER = "x-csrf-token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def get_current_session(request: Request, db: Session = Depends(get_db)) -> UserSession:
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        raise Unauthorized("Sessão não encontrada.")
    sess = db.scalar(select(UserSession).where(UserSession.token_hash == token_hash(raw)))
    now = utcnow()
    s = get_settings()
    if (
        sess is None
        or sess.revoked_at is not None
        or sess.expires_at <= now
        or sess.last_seen_at + timedelta(minutes=s.session_idle_minutes) <= now
        or not sess.user.is_active
    ):
        raise Unauthorized("Sessão expirada. Entre novamente.")

    # CSRF (double submit): toda requisição que altera estado precisa do cabeçalho
    # com o token emitido no login, que é comparado ao hash guardado na sessão.
    if request.method not in SAFE_METHODS:
        header = request.headers.get(CSRF_HEADER, "")
        if not header or not constant_time_equals(token_hash(header), sess.csrf_hash):
            raise Forbidden("Token CSRF inválido.")

    if now - sess.last_seen_at > timedelta(minutes=1):
        sess.last_seen_at = now
        db.commit()
    request.state.session_id = sess.id
    return sess


def current_user(sess: UserSession = Depends(get_current_session)) -> User:
    return sess.user


def require_permission(*permissions: str) -> Callable[..., User]:
    def _dep(user: User = Depends(current_user)) -> User:
        missing = set(permissions) - user.permission_keys
        if missing:
            raise Forbidden("Você não tem permissão para esta ação.")
        return user

    return _dep


def require_module(key: str) -> Callable[..., None]:
    def _dep(db: Session = Depends(get_db)) -> None:
        mod = db.scalar(select(Module).where(Module.key == key))
        if mod is None or not mod.enabled:
            raise NotFound("Módulo desativado.")

    return _dep
