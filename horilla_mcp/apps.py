from django.apps import AppConfig


class HorillaMcpConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "horilla_mcp"

    def ready(self):
        from horilla_mcp import sidebar  # noqa: F401
