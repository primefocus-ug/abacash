"""
python manage.py delete_fake_tenants            # dry run — lists what WOULD be deleted
python manage.py delete_fake_tenants --execute   # actually deletes

Removes the bot-signup tenants confirmed as fake: their Company + Domain
rows in the public schema, plus their Postgres schema (DROP SCHEMA ...
CASCADE) if one happens to exist for them. Company.delete() (TenantMixin)
handles dropping the schema and the Domain row(s) automatically — this
command's job is just to make sure nothing runs without an explicit
--execute, and to print a clear record of exactly what was removed.
"""
from django.core.management.base import BaseCommand

FAKE_SCHEMAS = [
    "miyrwvgrup","ngzdtpzwrv","xrlgunstul","lomsuotjgf","ofktitdsfi","wkmullmzuw",
    "fjvoeoyyyy","wxvpemiuum","pikyhjonjn","htvinesnze","jxpumwlrut","psdnhetjhm",
    "sreuzjrnht","vxrdltwvtw","termine","puooppkpqr","swhneijeke","hqfewuxjvd",
    "xsxeisghdr","svxymrqeml","dxlmmnngij","pmypsywizz","nwosfmtoew","fnuuexerwg",
    "jtlglieifd","uwpoodkjop","iwytwjmmxn","yljfyeiwhl","yfuplhntlo","zhtffnwthp",
    "evhyfggdnm","iettfvmjpm","kyxswxwsrr","zflevoyslr","iiphhmxlmj","zerizowvsr",
    "mstgpjkqoj","fwxuiifqwt","ynwdehfhdl","nvhrtrzqrs","vilgjrjwtr","ddhlvdejpx",
    "xfyeutxdtu","yztjtgvqwl","tzzsrqokrr","gqlhugljmp","xdlpzgjrwg","iowmpmwnzf",
    "etrhnotsek","jgyjphgmvy","ihmevtmefm","zjzjhzkeww","kxywvdvzqv","xypqekqouj",
    "rwuvzqyfyh","sestlgplfu","fthjqxgirn",
]


class Command(BaseCommand):
    help = "Delete the confirmed-fake bot-signup tenants. Dry run unless --execute is passed."

    def add_arguments(self, parser):
        parser.add_argument("--execute", action="store_true", default=False,
                             help="Actually delete. Without this flag, only lists what would happen.")

    def handle(self, *args, **options):
        from tenants.models import Company

        execute = options["execute"]
        mode = "DELETING" if execute else "DRY RUN (nothing will be deleted — pass --execute to actually delete)"
        self.stdout.write(f"{mode}\n")

        found, missing = [], []
        for schema in FAKE_SCHEMAS:
            c = Company.objects.filter(schema_name=schema).first()
            if c:
                found.append(c)
            else:
                missing.append(schema)

        for c in found:
            label = f"{c.schema_name:14s} name={c.name!r}"
            if execute:
                c.delete()
                self.stdout.write(self.style.SUCCESS(f"  deleted: {label}"))
            else:
                self.stdout.write(f"  would delete: {label}")

        if missing:
            self.stdout.write(f"\n{len(missing)} already gone / no matching Company row (skipped):")
            for schema in missing:
                self.stdout.write(f"  {schema}")

        self.stdout.write("")
        if execute:
            self.stdout.write(self.style.SUCCESS(f"Done — {len(found)} tenant(s) deleted."))
        else:
            self.stdout.write(self.style.WARNING(
                f"{len(found)} tenant(s) would be deleted. Re-run with --execute to actually do it."
            ))
