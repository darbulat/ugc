"""Authenticated recipient snapshots; external 32-byte key, no fallback."""

import base64
import hashlib
import hmac
import json
import os
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class PayoutRequisitesCrypto:
    def __init__(self, key: str, key_id: str):
        try:
            decoded = base64.b64decode(key, altchars=b"-_", validate=True)
        except (ValueError, TypeError):
            decoded = b""
        if len(decoded) != 32 or not key_id.strip():
            raise ValueError("payout_encryption_configuration_required")
        self._key, self.key_id = decoded, key_id.strip()
        self._aead = AESGCM(decoded)

    def fingerprint(self, details: dict[str, str], recipient_id: UUID) -> str:
        plain = self._encode(details)
        return hmac.new(
            self._key,
            b"payout-fingerprint:" + str(recipient_id).encode() + plain,
            hashlib.sha256,
        ).hexdigest()

    @staticmethod
    def _encode(details):
        if (
            not isinstance(details, dict)
            or not details
            or len(details) > 30
            or any(
                not isinstance(k, str)
                or not k.strip()
                or len(k) > 64
                or not isinstance(v, str)
                or not v.strip()
                or len(v) > 2000
                for k, v in details.items()
            )
        ):
            raise ValueError("payout_requisites_fields_invalid")
        encoded = json.dumps(
            details, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
        if len(encoded) > 20000:
            raise ValueError("payout_requisites_fields_invalid")
        return encoded

    @staticmethod
    def _context(recipient_id, identity):
        return f"ugc:payout-requisites:{recipient_id}:{identity}".encode()

    def seal(self, details, recipient_id, identity):
        plain = self._encode(details)
        nonce = os.urandom(12)
        encrypted = nonce + self._aead.encrypt(
            nonce, plain, self._context(recipient_id, identity)
        )
        account = details.get("bank_account", "")
        return dict(
            ciphertext=encrypted,
            key_id=self.key_id,
            fingerprint=self.fingerprint(details, recipient_id),
            masked_label="••••" + account[-4:],
        )

    def open(self, record, recipient_id, identity):
        try:
            if record["key_id"] != self.key_id:
                raise ValueError()
            value = bytes(record["ciphertext"])
            plain = self._aead.decrypt(
                value[:12], value[12:], self._context(recipient_id, identity)
            )
            details = json.loads(plain)
            self._encode(details)
            if not hmac.compare_digest(
                record["fingerprint"], self.fingerprint(details, recipient_id)
            ):
                raise ValueError()
            return details
        except (
            InvalidTag,
            ValueError,
            KeyError,
            TypeError,
            UnicodeError,
        ) as error:
            raise ValueError(
                "payout_requisites_authentication_failed"
            ) from error
