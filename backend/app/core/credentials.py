"""Persistência de credenciais cifradas.

Único ponto do código que decifra segredos. ``load_secret`` deve ser chamado
somente pelos componentes que realmente usam a credencial (validação, worker de
sincronização e entrega de notificações). Nenhuma rota devolve o conteúdo.
"""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.crypto import EncryptedBlob, get_vault
from app.models import EncryptedCredential
from app.models.base import utcnow


def store_secret(
    db: Session, *, owner_type: str, owner_id: uuid.UUID, user_id: uuid.UUID, secret: dict, hint: str | None
) -> EncryptedCredential:
    blob = get_vault().encrypt(secret, owner_type=owner_type, owner_id=str(owner_id), user_id=str(user_id))
    row = db.scalar(
        select(EncryptedCredential).where(
            EncryptedCredential.owner_type == owner_type, EncryptedCredential.owner_id == owner_id
        )
    )
    if row is None:
        row = EncryptedCredential(owner_type=owner_type, owner_id=owner_id, user_id=user_id)
        db.add(row)
    row.key_version, row.nonce, row.ciphertext, row.hint = blob.key_version, blob.nonce, blob.ciphertext, hint
    row.updated_at = utcnow()
    return row


def load_secret(db: Session, *, owner_type: str, owner_id: uuid.UUID, user_id: uuid.UUID) -> dict | None:
    row = db.scalar(
        select(EncryptedCredential).where(
            EncryptedCredential.owner_type == owner_type,
            EncryptedCredential.owner_id == owner_id,
            EncryptedCredential.user_id == user_id,
        )
    )
    if row is None:
        return None
    return get_vault().decrypt(
        EncryptedBlob(row.key_version, row.nonce, row.ciphertext),
        owner_type=owner_type,
        owner_id=str(owner_id),
        user_id=str(user_id),
    )


def credential_hint(db: Session, owner_type: str, owner_id: uuid.UUID) -> tuple[str | None, object | None]:
    row = db.scalar(
        select(EncryptedCredential).where(
            EncryptedCredential.owner_type == owner_type, EncryptedCredential.owner_id == owner_id
        )
    )
    return (row.hint, row.updated_at) if row else (None, None)


def delete_secret(db: Session, owner_type: str, owner_id: uuid.UUID) -> None:
    db.execute(
        delete(EncryptedCredential).where(
            EncryptedCredential.owner_type == owner_type, EncryptedCredential.owner_id == owner_id
        )
    )


def rotate_all(db: Session) -> int:
    """Recifra todas as credenciais com a versão de chave ativa."""
    vault = get_vault()
    n = 0
    for row in db.scalars(select(EncryptedCredential).where(EncryptedCredential.key_version != vault.active_version)):
        aad = {"owner_type": row.owner_type, "owner_id": str(row.owner_id), "user_id": str(row.user_id)}
        secret = vault.decrypt(EncryptedBlob(row.key_version, row.nonce, row.ciphertext), **aad)
        blob = vault.encrypt(secret, **aad)
        row.key_version, row.nonce, row.ciphertext = blob.key_version, blob.nonce, blob.ciphertext
        row.updated_at = utcnow()
        n += 1
    db.commit()
    return n
