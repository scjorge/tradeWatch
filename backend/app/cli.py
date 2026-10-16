"""Comandos administrativos.

    python -m app.cli seed                  # papéis, permissões, módulos e corretoras (idempotente)
    python -m app.cli create-admin EMAIL    # cria/promove administrador (senha pedida no terminal)
    python -m app.cli rotate-keys           # recifra credenciais com a versão de chave ativa
    python -m app.cli generate-key          # imprime uma nova chave AES-256 em base64
"""

from __future__ import annotations

import argparse
import getpass
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import session_factory
from app.models import ExchangeProvider, Module, Permission, Role, User


def seed(db: Session) -> None:
    from app.integrations.registry import ADAPTERS
    from app.modules.registry import REGISTRY

    perms: dict[str, Permission] = {p.key: p for p in db.scalars(select(Permission))}
    for spec in REGISTRY:
        for key, desc in spec.permissions.items():
            if key not in perms:
                perms[key] = Permission(key=key, description=desc)
                db.add(perms[key])
            else:
                perms[key].description = desc
        mod = db.scalar(select(Module).where(Module.key == spec.key))
        if mod is None:
            db.add(Module(key=spec.key, name=spec.name, description=spec.description, version=spec.version, enabled=True))
        else:
            mod.name, mod.description, mod.version = spec.name, spec.description, spec.version
    db.flush()

    role_names = {"user": "Usuário", "admin": "Administrador"}
    for rkey, rname in role_names.items():
        role = db.scalar(select(Role).where(Role.key == rkey))
        if role is None:
            role = Role(key=rkey, name=rname)
            db.add(role)
        wanted = {p for spec in REGISTRY for p in spec.role_permissions.get(rkey, [])}
        role.permissions = [perms[k] for k in sorted(wanted)]

    for key, cls in ADAPTERS.items():
        prov = db.scalar(select(ExchangeProvider).where(ExchangeProvider.key == key))
        caps = {
            "deposits": cls.info.capabilities.deposits,
            "withdrawals": cls.info.capabilities.withdrawals,
            "orders": cls.info.capabilities.orders,
        }
        if prov is None:
            db.add(ExchangeProvider(key=key, name=cls.info.name, enabled=True, capabilities=caps))
        else:
            prov.name, prov.capabilities = cls.info.name, caps
    # Remove módulos e permissões que saíram do código (ex.: módulos descontinuados).
    known_modules = {spec.key for spec in REGISTRY}
    for mod in db.scalars(select(Module)).all():
        if mod.key not in known_modules:
            db.delete(mod)
    known_perms = {k for spec in REGISTRY for k in spec.permissions}
    for perm in db.scalars(select(Permission)).all():
        if perm.key not in known_perms:
            db.delete(perm)
    db.commit()


def create_admin(db: Session, email: str, password: str | None) -> None:
    from app.core.security import hash_password, validate_password_strength
    from app.models.base import utcnow

    email = email.strip().lower()
    admin = db.scalar(select(Role).where(Role.key == "admin"))
    user_role = db.scalar(select(Role).where(Role.key == "user"))
    if admin is None:
        sys.exit("Execute 'seed' antes.")
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        if not password:
            password = getpass.getpass("Senha do administrador: ")
        validate_password_strength(password)
        user = User(email=email, password_hash=hash_password(password), display_name="Administrador", email_verified_at=utcnow())
        db.add(user)
    for r in (admin, user_role):
        if r and r not in user.roles:
            user.roles.append(r)
    db.commit()
    print(f"Administrador pronto: {email}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="app.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("seed")
    ca = sub.add_parser("create-admin")
    ca.add_argument("email")
    ca.add_argument("--password-stdin", action="store_true", help="Lê a senha da entrada padrão")
    sub.add_parser("rotate-keys")
    sub.add_parser("generate-key")
    args = parser.parse_args(argv)

    if args.cmd == "generate-key":
        from app.core.crypto import generate_key_b64

        print(generate_key_b64())
        return
    with session_factory()() as db:
        if args.cmd == "seed":
            seed(db)
            print("Seed concluído.")
        elif args.cmd == "create-admin":
            pw = sys.stdin.readline().strip() if args.password_stdin else None
            create_admin(db, args.email, pw)
        elif args.cmd == "rotate-keys":
            from app.core.credentials import rotate_all

            print(f"{rotate_all(db)} credencial(is) recifrada(s).")


if __name__ == "__main__":
    main()
