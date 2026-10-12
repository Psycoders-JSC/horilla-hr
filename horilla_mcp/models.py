import hashlib
import secrets

from django.conf import settings
from django.db import models


def hash_token(token):
    return hashlib.sha256(token.encode()).hexdigest()


class McpToken(models.Model):
    """One MCP access token per user; only the SHA-256 is stored."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="mcp_token"
    )
    token_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    @classmethod
    def issue(cls, user):
        """Create or replace the user's token; returns the plain token (shown once)."""
        token = secrets.token_urlsafe(32)
        cls.objects.update_or_create(user=user, defaults={"token_hash": hash_token(token), "last_used_at": None})
        return token
