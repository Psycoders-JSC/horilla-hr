import os

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import render
from django.views.decorators.http import require_POST

from horilla_mcp.models import McpToken


def can_use_mcp(user):
    # The tools hire, reject and edit employees, so require those rights.
    return user.has_perm("recruitment.change_candidate") and user.has_perm(
        "employee.change_employee"
    )


def _mcp_url(request):
    base = os.environ.get("MCP_PUBLIC_URL") or f"https://mcp.{request.get_host()}"
    return base.rstrip("/") + "/mcp"


def _render(request, token=None):
    url = _mcp_url(request)
    return render(
        request,
        "horilla_mcp/access.html",
        {
            "token": token,
            "url": url,
            "has_token": McpToken.objects.filter(user=request.user).exists(),
            "cli": f'claude mcp add --transport http horilla {url} --header "Authorization: Bearer {token}"'
            if token
            else None,
            "connector_url": f"{url}?token={token}" if token else None,
        },
    )


@login_required
def access(request):
    if not can_use_mcp(request.user):
        return HttpResponseForbidden()
    return _render(request)


@login_required
@require_POST
def generate(request):
    if not can_use_mcp(request.user):
        return HttpResponseForbidden()
    return _render(request, McpToken.issue(request.user))


@login_required
@require_POST
def revoke(request):
    McpToken.objects.filter(user=request.user).delete()
    return _render(request)
