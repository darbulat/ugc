"""Dedicated HMAC tokens are reconstructed only for a current owner view."""

import base64
import binascii
import hashlib
import hmac
import json
import re
from dataclasses import asdict

from pydantic import SecretStr

from ugc_bot.domain.messenger_linking import LinkContext, LinkScope


def token_verifier(token: str) -> str:
    if not re.fullmatch(r"lk1_[A-Za-z0-9_-]{43}", token):
        raise ValueError("invalid_link_token")
    return hashlib.sha256(token.encode("ascii")).hexdigest()


class LinkTokens:
    def __init__(self, secret: SecretStr, scope: LinkScope):
        value = secret.get_secret_value()
        try:
            if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
                raise ValueError
            self._key = base64.b64decode(
                value + "=" * (-len(value) % 4), altchars=b"-_", validate=True
            )
            if (
                len(self._key) < 32
                or base64.urlsafe_b64encode(self._key).decode().rstrip("=")
                != value
            ):
                raise ValueError
        except (ValueError, binascii.Error):
            raise ValueError("link_key_unavailable") from None
        if (
            scope.bot_id <= 0
            or not re.fullmatch(r"[0-9a-f]{64}", scope.max_bot_fingerprint)
            or not re.fullmatch(
                r"[A-Za-z][A-Za-z0-9_]{4,31}", scope.bot_username
            )
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", scope.key_id)
        ):
            raise ValueError("link_scope_unavailable")
        self.scope = scope

    def derive(self, context: LinkContext) -> str:
        if context.scope != self.scope:
            raise ValueError("link_scope_unavailable")
        data = json.dumps(
            asdict(context), sort_keys=True, separators=(",", ":"), default=str
        ).encode()
        value = hmac.new(
            self._key, b"ugc:messenger-link:v1\0" + data, hashlib.sha256
        ).digest()
        return "lk1_" + base64.urlsafe_b64encode(value).decode("ascii").rstrip(
            "="
        )

    @staticmethod
    def verifier(token: str) -> str:
        return token_verifier(token)

    def matches(self, token: str, context: LinkContext) -> bool:
        return hmac.compare_digest(
            self.verifier(token), self.verifier(self.derive(context))
        )

    def launch_url(self, context: LinkContext) -> str:
        return f"https://t.me/{self.scope.bot_username}?start={self.derive(context)}"
