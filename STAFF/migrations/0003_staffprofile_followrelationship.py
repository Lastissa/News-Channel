from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("STAFF", "0002_staffprofile_get_blog_notification"),
    ]

    operations = [
        migrations.CreateModel(
            name="FollowRelationship",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("followee", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="followers", to="STAFF.staffprofile")),
                ("follower", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="following", to="STAFF.staffprofile")),
            ],
            options={
                "constraints": [models.UniqueConstraint(fields=("follower", "followee"), name="unique_staff_follow_relation")],
            },
        ),
    ]
