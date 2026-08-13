# Registers the app-level permissions defined in accounts/permissions.py
# on the User model's Meta.permissions. Django's post_migrate signal
# creates the actual Permission rows automatically once this runs — no
# data migration needed just for the permissions themselves (the Groups
# and role->group backfill are handled separately in 0007).

from django.db import migrations

from accounts.permissions import PERMISSIONS


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0005_alter_user_managers_alter_user_username'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='user',
            options={
                'ordering': ['first_name', 'last_name'],
                'verbose_name': 'User',
                'verbose_name_plural': 'Users',
                'permissions': [(codename, label) for codename, label, _groups in PERMISSIONS],
            },
        ),
    ]
