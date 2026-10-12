from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _

from horilla.menu import settings_menu
from horilla_mcp.views import can_use_mcp


@settings_menu.register
class McpSettings:
    title = _("AI Integration")
    order = 61
    items = [
        {
            "label": _("MCP Access"),
            "url": reverse_lazy("mcp-access"),
            "accessibility": lambda request, *a, **kw: can_use_mcp(request.user),
            "search_entries": [
                {
                    "text": _("MCP Access"),
                    "description": _("Generate a token to connect Claude to Horilla"),
                }
            ],
        }
    ]
