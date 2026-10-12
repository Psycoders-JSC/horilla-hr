"""
Serve the Horilla MCP tools over streamable HTTP (http://host:8100/mcp).

    MCP_TOKEN=... python manage.py run_mcp

Clients authenticate with ``Authorization: Bearer <token>`` or ``?token=``, where the
token is MCP_TOKEN or a per-user token generated in Settings > MCP Access.
"""

import hmac
import os
from urllib.parse import parse_qs

import uvicorn
from django.core.management.base import BaseCommand, CommandError
from starlette.responses import PlainTextResponse


def _user_token_ok(supplied):
    from django.utils import timezone

    from horilla_mcp.models import McpToken, hash_token

    # ponytail: sync ORM call on the event loop, fine at this traffic
    return bool(supplied) and bool(
        McpToken.objects.filter(token_hash=hash_token(supplied.decode())).update(
            last_used_at=timezone.now()
        )
    )


class TokenAuth:
    """ASGI middleware: 401 unless the request carries a valid token."""

    def __init__(self, app, token):
        self.app = app
        self.token = token.encode()

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            auth = dict(scope["headers"]).get(b"authorization", b"")
            if auth.lower().startswith(b"bearer "):
                supplied = auth[7:].strip()
            else:
                query = parse_qs(scope["query_string"].decode())
                supplied = query.get("token", [""])[0].encode()
            if not (
                hmac.compare_digest(supplied, self.token) or _user_token_ok(supplied)
            ):
                response = PlainTextResponse("Unauthorized", status_code=401)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


class Command(BaseCommand):
    help = "Run the Horilla MCP server (streamable HTTP, token protected)."

    def add_arguments(self, parser):
        parser.add_argument("--port", type=int, default=8100)

    def handle(self, *args, **options):
        token = os.environ.get("MCP_TOKEN")
        if not token:
            raise CommandError("MCP_TOKEN is not set")
        # ponytail: ORM calls run on the event-loop thread (one agent at a time);
        # move tools to a thread pool if concurrent callers ever matter.
        os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
        from horilla_mcp.server import mcp

        app = TokenAuth(mcp.streamable_http_app(), token)
        uvicorn.run(app, host="0.0.0.0", port=options["port"])
