from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.audit import audit, client_ip
from app.core.deps import SESSION_COOKIE, get_current_session
from app.core.ratelimit import limiter
from app.core.security import token_hash
from app.db import get_db
from app.models import UserSession
from app.models.base import utcnow
from app.modules.auth import service
from app.modules.users.schemas import UserOut, user_out

router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)
    display_name: str = Field(default="", max_length=120)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class EmailIn(BaseModel):
    email: EmailStr


class TokenIn(BaseModel):
    token: str = Field(min_length=10, max_length=200)


class ResetIn(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    new_password: str = Field(min_length=1, max_length=256)


def _limit(request: Request, bucket: str, extra: str = "") -> None:
    per_min = get_settings().rate_limit_auth_per_minute
    limiter.hit(f"{bucket}:ip:{client_ip(request)}", per_min)
    if extra:
        limiter.hit(f"{bucket}:id:{extra.lower()}", max(3, per_min // 2))


@router.post("/register", status_code=202)
def register(body: RegisterIn, request: Request, db: Session = Depends(get_db)):
    _limit(request, "register", body.email)
    service.register(db, body.email, body.password, body.display_name, request)
    return {"message": "Se o cadastro for válido, você receberá um e-mail para confirmar a conta."}


@router.post("/login", response_model=UserOut)
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    _limit(request, "login", body.email)
    user = service.login(db, body.email, body.password, request, response)
    return user_out(user)


@router.post("/logout", status_code=204)
def logout(request: Request, sess: UserSession = Depends(get_current_session), db: Session = Depends(get_db)):
    db_sess = db.get(UserSession, sess.id)
    if db_sess:
        db_sess.revoked_at = utcnow()
    audit(db, "auth.logout", user_id=sess.user_id, request=request)
    db.commit()
    response = Response(status_code=204)
    service.clear_session_cookies(response)
    return response


@router.post("/verify-email")
def verify_email(body: TokenIn, request: Request, db: Session = Depends(get_db)):
    _limit(request, "verify")
    user = service.consume_token(db, body.token, service.VERIFY_EMAIL)
    user.email_verified_at = user.email_verified_at or utcnow()
    audit(db, "auth.email_verified", user_id=user.id, request=request)
    db.commit()
    return {"message": "E-mail confirmado. Você já pode entrar."}


@router.post("/resend-verification", status_code=202)
def resend_verification(body: EmailIn, request: Request, db: Session = Depends(get_db)):
    from sqlalchemy import select

    from app.models import User

    _limit(request, "resend", body.email)
    user = db.scalar(select(User).where(User.email == service.normalize_email(body.email)))
    if user and user.email_verified_at is None:
        service.send_verification(db, user)
        db.commit()
    return {"message": "Se houver uma conta pendente, um novo e-mail foi enviado."}


@router.post("/forgot-password", status_code=202)
def forgot_password(body: EmailIn, request: Request, db: Session = Depends(get_db)):
    _limit(request, "forgot", body.email)
    service.forgot_password(db, body.email, request)
    return {"message": "Se o e-mail estiver cadastrado, você receberá instruções."}


@router.post("/reset-password")
def reset_password(body: ResetIn, request: Request, db: Session = Depends(get_db)):
    _limit(request, "reset")
    service.reset_password(db, body.token, body.new_password, request)
    return {"message": "Senha redefinida. Entre novamente."}


@router.get("/session")
def session_info(request: Request, sess: UserSession = Depends(get_current_session)):
    """Usado pelo frontend para descobrir se há sessão ativa."""
    current = request.cookies.get(SESSION_COOKIE, "")
    return {"user": user_out(sess.user), "session_id": str(sess.id), "current": token_hash(current) == sess.token_hash}
