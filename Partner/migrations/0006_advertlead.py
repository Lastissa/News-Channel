# Generated manually for the partner-page lead form.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("Partner", "0005_advertlandingpage"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AdvertLead",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "plan",
                    models.CharField(
                        choices=[
                            ("regular", "Regular"),
                            ("pro", "Pro"),
                            ("advance", "Advance"),
                        ],
                        max_length=20,
                    ),
                ),
                ("business_name", models.CharField(max_length=120)),
                ("contact_email", models.EmailField(max_length=254)),
                (
                    "whatsapp_number",
                    models.CharField(blank=True, default="", max_length=32),
                ),
                ("business_details", models.TextField(max_length=2000)),
                (
                    "created_at",
                    models.DateTimeField(auto_now_add=True, db_index=True),
                ),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="advert_leads",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ("-created_at",),
            },
        ),
    ]
