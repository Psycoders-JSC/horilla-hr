import base64
import hashlib
import hmac
import secrets

from django.conf import settings
from django.db import models


def hash_token(token):
    return hashlib.sha256(token.encode()).hexdigest()


def _derive(nonce):
    """Token = HMAC(SECRET_KEY, nonce): re-showable, yet a DB dump alone can't reveal it."""
    digest = hmac.new(settings.SECRET_KEY.encode(), f"mcp:{nonce}".encode(), "sha256").digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


class McpToken(models.Model):
    """One MCP access token per user; the server only checks the SHA-256."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="mcp_token"
    )
    token_hash = models.CharField(max_length=64, unique=True)
    nonce = models.CharField(max_length=32, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    @property
    def token(self):
        """The plain token, or None if it can't be rebuilt (legacy row or SECRET_KEY changed)."""
        token = _derive(self.nonce) if self.nonce else None
        return token if token and hash_token(token) == self.token_hash else None

    @classmethod
    def issue(cls, user):
        """Create or replace the user's token; returns the plain token."""
        nonce = secrets.token_hex(16)
        token = _derive(nonce)
        cls.objects.update_or_create(
            user=user,
            defaults={"token_hash": hash_token(token), "nonce": nonce, "last_used_at": None},
        )
        return token
