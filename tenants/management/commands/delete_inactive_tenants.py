"""
python manage.py delete_inactive_tenants            # dry run — lists what WOULD be deleted
python manage.py delete_inactive_tenants --execute   # actually deletes

Removes the bot-signup tenants confirmed via check_remaining_tenants.py:
each has a real, fully-provisioned schema (2 seed users, default branch/
products) but zero clients, zero loans, and no user has ever logged in.
Company.delete() (TenantMixin) drops the schema and Domain row(s) too.
"""
from django.core.management.base import BaseCommand

INACTIVE_SCHEMAS = [
    "vsfivpxekl","xynpdqzvgl","nimoteqgfw","jsvhsrgixg","idpqrvvxmz","gwoxkdpqde",
    "ewzrfqdkxy","mgdqtffrzx","nvwdetighd","knwftplmqt","pnvpjdninm","qhiynwztwl",
    "uwjofeqxhu","jswprrpefm","pqopyfdvnx","otlnuwkten","ndthwghqtn","qwvunupllw",
    "kouoodsgsw","iyktvjxprq","epjdwnxnkk","mgpegnyyyq","euoyhqfxrg","rhmpiflpsm",
    "kjkeeqephh","xlqjetoryl","gzshjjnpvu","lvydrgfkxh","vjsizqfppz","ithpmetgqj",
    "zmrqwmesyz","yqlemywnrm","tehmtzqhkq","vpsosfskww","pwdvygmupw","yglnnyhlrn",
    "rymtlfdddx","osthefurnd","jvusihzpis","gwpjtggekd","eyfpwypphl","ynpsvzsxdr",
    "mgxzdkqfpl","ydlrwletmj","tqlxodsvhh","dsvmxofzdr","lkruzwvwfp","yqxnlesxmp",
    "vkddfqiihk","iflltmshyh","hhepifjniq","ijngzroxkg","ldyjdxxyld","smklynturd",
    "uuuxlzkinp","pukeegupjx","luskhnjgmw","unrifjzunt","pujomhkurk","zzjxvpzvpt",
    "nwowxtfisn","nrnhxmhygg","ufquvwhdsl","mmhgviyqix","prnjhjqqfk","fhlzlendln",
    "plzusrkxfr","vsxllssgfu","nluotxokxo","wsjvdkzono","wlyigvjown","gfmdeqfdqv",
    "ppwouzrrfd","iozpyjwgsq","rtillpgozz","sgjmxojwur","sgmxmhexnr","wmnkrueevj",
    "mwporomewr","xdnnnjqzom","mouvprfips","hzspnydfom","lvtvtrsoql","ghdgyzoiji",
    "seffevdyul","zwofnffeff","ezvvsoldqi",
    "egwymsyzjk",  # schema exists but never finished migrating — incomplete, no data
]


class Command(BaseCommand):
    help = "Delete the confirmed-inactive bot-signup tenants. Dry run unless --execute is passed."

    def add_arguments(self, parser):
        parser.add_argument("--execute", action="store_true", default=False,
                             help="Actually delete. Without this flag, only lists what would happen.")

    def handle(self, *args, **options):
        from tenants.models import Company

        execute = options["execute"]
        mode = "DELETING" if execute else "DRY RUN (nothing will be deleted — pass --execute to actually delete)"
        self.stdout.write(f"{mode}\n")

        found, missing = [], []
        for schema in INACTIVE_SCHEMAS:
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
