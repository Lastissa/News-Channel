from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('STAFF', '0012_alter_staffprofile_role'),
    ]

    operations = [
        migrations.AddField(
            model_name='staffprofile',
            name='get_follower_notification',
            field=models.BooleanField(default=True, help_text='WETHER TO EMAIL THE AUTHOR WHEN SOMEONE STARTS FOLLOWING THEM'),
        ),
    ]
