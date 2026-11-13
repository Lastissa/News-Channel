from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ADMIN", "0003_sitesettings_archive_upload_alerts"),
    ]

    operations = [
        migrations.AddField(
            model_name="sitesettings",
            name="ads_whatsapp_support",
            field=models.CharField(
                blank=True,
                default="",
                help_text="WhatsApp number for advertising and partnership enquiries.",
                max_length=32,
            ),
        ),
    ]
