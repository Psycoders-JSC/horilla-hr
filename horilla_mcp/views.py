import json
import os

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import redirect, render
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


def _tools():
    from horilla_mcp.server import mcp

    # ponytail: private FastMCP attr; switch to `await mcp.list_tools()` if it moves
    return [
        {"name": t.name, "description": " ".join((t.description or "").split())}
        for t in mcp._tool_manager.list_tools()
    ]


def _prompt(url, token, tools):
    tool_lines = "\n".join(f"- {t['name']}: {t['description']}" for t in tools)
    return f"""You have access to Horilla HR through an MCP server (streamable HTTP).

Connection
- URL: {url}
- Auth: send the header "Authorization: Bearer {token}" (or append ?token={token} to the URL).
- If your client cannot add MCP servers, call the URL directly with JSON-RPC 2.0 over HTTP POST:
  "initialize" first, then "tools/list" and "tools/call". Send "Accept: application/json, text/event-stream"
  and echo back the "Mcp-Session-Id" response header on later requests.

How to work
- Never guess IDs. Look them up first with list_recruitments, list_job_positions, list_candidates,
  list_employees, list_reject_reasons or list_talent_pools.
- List tools return 50 rows per page with total/page metadata; pass page=2, 3... for more.
- Failures come back as {{"error": "..."}}. Read the message, fix the input and retry; do not loop blindly.
- update_* tools accept only the allow-listed fields named in their description.
- Dates use YYYY-MM-DD.
- Ask me before anything hard to undo: reject_candidate, hire_candidate (especially with convert=True),
  set_employee_active, and bulk add_candidates. Summarise what you will change and wait for a yes.
- After making changes, report what changed, with the IDs.

Available tools
{tool_lines}

Treat the token like a password: don't print it back, log it or send it anywhere else."""


@login_required
def access(request):
    if not can_use_mcp(request.user):
        return HttpResponseForbidden()
    record = McpToken.objects.filter(user=request.user).first()
    token = record.token if record else None
    url = _mcp_url(request)
    tools = _tools()
    context = {"record": record, "token": token, "url": url, "tools": tools}
    if token:
        auth = f"Bearer {token}"
        context |= {
            "cli": f'claude mcp add --transport http horilla {url} --header "Authorization: {auth}"',
            "connector_url": f"{url}?token={token}",
            "json_config": json.dumps(
                {"mcpServers": {"horilla": {"type": "http", "url": url, "headers": {"Authorization": auth}}}},
                indent=2,
            ),
            "desktop_config": json.dumps(
                {
                    "mcpServers": {
                        "horilla": {
                            "command": "npx",
                            "args": ["-y", "mcp-remote", url, "--header", f"Authorization:{auth}"],
                        }
                    }
                },
                indent=2,
            ),
            "curl": f'curl -i {url} -H "Authorization: {auth}" -H "Content-Type: application/json" '
            f'-H "Accept: application/json, text/event-stream" '
            '-d \'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26",'
            '"capabilities":{},"clientInfo":{"name":"curl","version":"1"}}}\'',
            "prompt": _prompt(url, token, tools),
        }
    return render(request, "horilla_mcp/access.html", context)


@login_required
@require_POST
def generate(request):
    if not can_use_mcp(request.user):
        return HttpResponseForbidden()
    McpToken.issue(request.user)
    return redirect("mcp-access")


@login_required
@require_POST
def revoke(request):
    McpToken.objects.filter(user=request.user).delete()
    return redirect("mcp-access")
