from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ADMIN", "0002_sitesettings_customer_support_mobile_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="sitesettings",
            name="archive_upload_alerts",
            field=models.BooleanField(
                default=False,
                help_text="Email the owner every time a new item is uploaded to the archive gallery.",
            ),
        ),
    ]
