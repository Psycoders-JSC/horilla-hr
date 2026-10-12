from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("horilla_mcp", "0001_initial")]

    operations = [
        migrations.AddField(
            model_name="mcptoken",
            name="nonce",
            field=models.CharField(blank=True, max_length=32),
        ),
    ]
