from django.urls import path

from horilla_mcp import views

urlpatterns = [
    path("settings/mcp/", views.access, name="mcp-access"),
    path("settings/mcp/generate/", views.generate, name="mcp-generate"),
    path("settings/mcp/revoke/", views.revoke, name="mcp-revoke"),
]
