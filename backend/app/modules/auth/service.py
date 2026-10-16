from __future__ import annotations

from datetime import timedelta

from fastapi import Request, Response
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.audit import audit, client_ip
from app.core.deps import CSRF_COOKIE, SESSION_COOKIE
from app.core.errors import AppError, Unauthorized
from app.core.mailer import send_email
from app.core.security import (
    hash_password,
    needs_rehash,
    new_token,
    token_hash,
    validate_password_strength,
    verify_password,
)
from app.models import Role, User, UserSession, UserToken
from app.models.base import utcnow

VERIFY_EMAIL = "verify_email"
RESET_PASSWORD = "reset_password"


def normalize_email(email: str) -> str:
    return email.strip().lower()


def issue_token(db: Session, user: User, purpose: str, ttl: timedelta) -> str:
    # Invalida tokens anteriores do mesmo propósito.
    db.execute(
        update(UserToken)
        .where(UserToken.user_id == user.id, UserToken.purpose == purpose, UserToken.used_at.is_(None))
        .values(used_at=utcnow())
    )
    raw = new_token()
    db.add(UserToken(user_id=user.id, purpose=purpose, token_hash=token_hash(raw), expires_at=utcnow() + ttl))
    return raw


def consume_token(db: Session, raw: str, purpose: str) -> User:
    tok = db.scalar(
        select(UserToken).where(UserToken.token_hash == token_hash(raw), UserToken.purpose == purpose)
    )
    if tok is None or tok.used_at is not None or tok.expires_at <= utcnow():
        raise AppError("Link inválido ou expirado.", code="invalid_token")
    tok.used_at = utcnow()
    user = db.get(User, tok.user_id)
    assert user is not None
    return user


def send_verification(db: Session, user: User) -> None:
    raw = issue_token(db, user, VERIFY_EMAIL, timedelta(hours=48))
    link = f"{get_settings().app_base_url}/verify-email#t={raw}"
    send_email(
        user.email,
        "Confirme seu e-mail no TradeWatch",
        f"Olá {user.display_name or ''},\n\nConfirme seu e-mail acessando:\n{link}\n\n"
        "O link expira em 48 horas. Se você não criou esta conta, ignore esta mensagem.",
    )


def register(db: Session, email: str, password: str, display_name: str, request: Request) -> None:
    email = normalize_email(email)
    validate_password_strength(password)
    existing = db.scalar(select(User).where(User.email == email))
    if existing:
        # Resposta idêntica para não revelar se o e-mail já existe.
        send_email(
            email,
            "Tentativa de cadastro no TradeWatch",
            "Recebemos um pedido de cadastro com este e-mail, que já possui conta. "
            "Se foi você, use 'Esqueci minha senha'. Caso contrário, ignore esta mensagem.",
        )
        audit(db, "auth.register_existing_email", user_id=existing.id, request=request)
        db.commit()
        return
    role = db.scalar(select(Role).where(Role.key == "user"))
    user = User(email=email, password_hash=hash_password(password), display_name=display_name.strip())
    if role:
        user.roles.append(role)
    if not get_settings().require_email_verification:
        user.email_verified_at = utcnow()
    db.add(user)
    db.flush()
    audit(db, "auth.register", user_id=user.id, request=request)
    if get_settings().require_email_verification:
        send_verification(db, user)
    db.commit()


def create_session(db: Session, user: User, request: Request, response: Response) -> UserSession:
    s = get_settings()
    raw, csrf = new_token(), new_token()
    sess = UserSession(
        user_id=user.id,
        token_hash=token_hash(raw),
        csrf_hash=token_hash(csrf),
        expires_at=utcnow() + timedelta(hours=s.session_ttl_hours),
        ip=client_ip(request),
        user_agent=request.headers.get("user-agent", "")[:300],
    )
    db.add(sess)
    max_age = s.session_ttl_hours * 3600
    response.set_cookie(
        SESSION_COOKIE, raw, max_age=max_age, httponly=True, secure=s.cookie_secure, samesite="lax", path="/"
    )
    # Cookie legível pelo frontend apenas para ecoar no cabeçalho X-CSRF-Token.
    response.set_cookie(
        CSRF_COOKIE, csrf, max_age=max_age, httponly=False, secure=s.cookie_secure, samesite="strict", path="/"
    )
    return sess


def clear_session_cookies(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")


def login(db: Session, email: str, password: str, request: Request, response: Response) -> User:
    s = get_settings()
    email = normalize_email(email)
    user = db.scalar(select(User).where(User.email == email))
    now = utcnow()
    generic = Unauthorized("E-mail ou senha incorretos.")

    if user and user.locked_until and user.locked_until > now:
        audit(db, "auth.login_locked", user_id=user.id, request=request)
        db.commit()
        raise AppError(
            "Conta temporariamente bloqueada por excesso de tentativas. Tente mais tarde.",
            code="account_locked",
            status_code=429,
        )

    if not verify_password(user.password_hash if user else None, password) or user is None:
        if user:
            user.failed_login_count += 1
            if user.failed_login_count >= s.login_max_attempts:
                user.locked_until = now + timedelta(minutes=s.login_lockout_minutes)
                user.failed_login_count = 0
                audit(db, "auth.account_locked", user_id=user.id, request=request)
            audit(db, "auth.login_failed", user_id=user.id, request=request)
        else:
            audit(db, "auth.login_failed_unknown", request=request)
        db.commit()
        raise generic

    if not user.is_active:
        raise generic
    if s.require_email_verification and user.email_verified_at is None:
        raise AppError(
            "Confirme seu e-mail antes de entrar. Verifique sua caixa de entrada.",
            code="email_not_verified",
            status_code=403,
        )

    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now
    create_session(db, user, request, response)
    audit(db, "auth.login", user_id=user.id, request=request)
    db.commit()
    return user


def revoke_user_sessions(db: Session, user_id, except_session_id=None) -> int:
    q = update(UserSession).where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
    if except_session_id is not None:
        q = q.where(UserSession.id != except_session_id)
    return db.execute(q.values(revoked_at=utcnow())).rowcount


def forgot_password(db: Session, email: str, request: Request) -> None:
    user = db.scalar(select(User).where(User.email == normalize_email(email)))
    if user and user.is_active:
        raw = issue_token(db, user, RESET_PASSWORD, timedelta(minutes=30))
        link = f"{get_settings().app_base_url}/reset-password#t={raw}"
        send_email(
            user.email,
            "Redefinição de senha do TradeWatch",
            f"Para redefinir sua senha, acesse:\n{link}\n\nO link expira em 30 minutos e só pode ser "
            "usado uma vez. Se você não pediu a redefinição, ignore esta mensagem.",
        )
        audit(db, "auth.password_reset_requested", user_id=user.id, request=request)
    db.commit()


def reset_password(db: Session, raw: str, new_password: str, request: Request) -> None:
    validate_password_strength(new_password)
    user = consume_token(db, raw, RESET_PASSWORD)
    user.password_hash = hash_password(new_password)
    user.password_changed_at = utcnow()
    user.failed_login_count = 0
    user.locked_until = None
    if user.email_verified_at is None:
        user.email_verified_at = utcnow()  # quem recebeu o link comprovou o acesso ao e-mail
    revoke_user_sessions(db, user.id)
    audit(db, "auth.password_reset", user_id=user.id, request=request)
    db.commit()


def change_password(db: Session, user: User, current: str, new: str, session_id, request: Request) -> None:
    if not verify_password(user.password_hash, current):
        audit(db, "auth.password_change_failed", user_id=user.id, request=request)
        db.commit()
        raise AppError("Senha atual incorreta.", code="invalid_password")
    validate_password_strength(new)
    user.password_hash = hash_password(new)
    user.password_changed_at = utcnow()
    revoke_user_sessions(db, user.id, except_session_id=session_id)
    audit(db, "auth.password_changed", user_id=user.id, request=request)
    db.commit()
