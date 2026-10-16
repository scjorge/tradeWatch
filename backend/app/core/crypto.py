"""Cofre de credenciais com AES-256-GCM e chaves versionadas.

- As chaves mestras ficam fora do banco (Docker secret / gerenciador de segredos).
- Cada registro guarda a versão da chave usada, permitindo rotação gradual.
- O AAD (dados associados) vincula o ciphertext ao dono: um ciphertext copiado
  para outro registro/usuário falha na verificação de autenticidade.
"""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class VaultError(Exception):
    pass


@dataclass(frozen=True)
class EncryptedBlob:
    key_version: int
    nonce: bytes
    ciphertext: bytes


def parse_keys(raw: str | None) -> dict[int, bytes]:
    keys: dict[int, bytes] = {}
    if not raw:
        return keys
    for line in raw.replace(",", "\n").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        version, _, b64 = line.partition(":")
        key = base64.b64decode(b64.strip())
        if len(key) != 32:
            raise VaultError(f"Chave versão {version} não possui 32 bytes.")
        keys[int(version)] = key
    return keys


class CredentialVault:
    def __init__(self, keys: dict[int, bytes], active_version: int | None = None):
        if not keys:
            raise VaultError("Nenhuma chave de criptografia configurada (CREDENTIALS_KEYS).")
        self._keys = keys
        self.active_version = active_version or max(keys)
        if self.active_version not in keys:
            raise VaultError("Versão de chave ativa inexistente.")

    @staticmethod
    def _aad(owner_type: str, owner_id: str, user_id: str) -> bytes:
        return f"tradewatch:{owner_type}:{owner_id}:{user_id}".encode()

    def encrypt(self, secret: dict, *, owner_type: str, owner_id: str, user_id: str) -> EncryptedBlob:
        nonce = os.urandom(12)
        aes = AESGCM(self._keys[self.active_version])
        plaintext = json.dumps(secret, separators=(",", ":")).encode()
        ct = aes.encrypt(nonce, plaintext, self._aad(owner_type, owner_id, user_id))
        return EncryptedBlob(self.active_version, nonce, ct)

    def decrypt(self, blob: EncryptedBlob, *, owner_type: str, owner_id: str, user_id: str) -> dict:
        key = self._keys.get(blob.key_version)
        if key is None:
            raise VaultError(f"Chave versão {blob.key_version} indisponível.")
        try:
            pt = AESGCM(key).decrypt(blob.nonce, blob.ciphertext, self._aad(owner_type, owner_id, user_id))
        except InvalidTag as exc:
            raise VaultError("Falha de autenticidade ao decifrar credencial.") from exc
        return json.loads(pt)


_vault: CredentialVault | None = None


def get_vault() -> CredentialVault:
    global _vault
    if _vault is None:
        from app.config import get_settings

        s = get_settings()
        _vault = CredentialVault(parse_keys(s.credentials_keys), s.credentials_active_key_version)
    return _vault


def set_vault(vault: CredentialVault | None) -> None:
    global _vault
    _vault = vault


def generate_key_b64() -> str:
    return base64.b64encode(AESGCM.generate_key(bit_length=256)).decode()
