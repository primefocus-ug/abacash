from django.db import migrations

from accounts.permissions import ALL_GROUPS, PERMISSIONS


def seed_groups(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    User = apps.get_model("accounts", "User")

    groups_by_name = {}
    for name in ALL_GROUPS:
        group, _created = Group.objects.get_or_create(name=name)
        groups_by_name[name] = group
        # Start clean each run so re-running this migration (e.g. after
        # editing accounts/permissions.py and faking/reapplying) reflects
        # the current PERMISSIONS list exactly.
        group.permissions.clear()

    for codename, _label, group_names in PERMISSIONS:
        try:
            perm = Permission.objects.get(codename=codename, content_type__app_label="accounts")
        except Permission.DoesNotExist:
            # Shouldn't happen if 0006 ran first, but don't hard-fail the
            # whole migration over one missing permission.
            continue
        for group_name in group_names:
            groups_by_name[group_name].permissions.add(perm)

    # Backfill: put every existing user into the Group matching their
    # current role, without touching the role field itself.
    role_to_group = {
        "CASHIER": groups_by_name.get("Cashier"),
        "MANAGER": groups_by_name.get("Manager"),
        "CEO": groups_by_name.get("CEO"),
    }
    for user in User.objects.all():
        group = role_to_group.get(user.role)
        if group:
            user.groups.add(group)


def unseed_groups(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name__in=ALL_GROUPS).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0006_user_app_permissions'),
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        migrations.RunPython(seed_groups, unseed_groups),
    ]
