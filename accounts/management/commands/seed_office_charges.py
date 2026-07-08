from decimal import Decimal
from django.core.management.base import BaseCommand
from accounts.models import OfficeChargeTier


class Command(BaseCommand):
    help = "Seed the database with initial office charge tiers"

    def handle(self, *args, **kwargs):
        tiers = [
            {
                "min_amount": Decimal("0"),
                "max_amount": Decimal("50000"),
                "office_charge": Decimal("4000"),
            },
            {
                "min_amount": Decimal("50001"),
                "max_amount": Decimal("100000"),
                "office_charge": Decimal("5000"),
            },
            {
                "min_amount": Decimal("100001"),
                "max_amount": Decimal("200000"),
                "office_charge": Decimal("8000"),
            },
            {
                "min_amount": Decimal("200001"),
                "max_amount": Decimal("300000"),
                "office_charge": Decimal("10000"),
            },
            {
                "min_amount": Decimal("300001"),
                "max_amount": Decimal("450000"),
                "office_charge": Decimal("12000"),
            },
            {
                "min_amount": Decimal("450001"),
                "max_amount": Decimal("600000"),
                "office_charge": Decimal("15000"),
            },
            {
                "min_amount": Decimal("600001"),
                "max_amount": Decimal("800000"),
                "office_charge": Decimal("20000"),
            },
            {
                "min_amount": Decimal("800001"),
                "max_amount": Decimal("1000000"),
                "office_charge": Decimal("30000"),
            },
            {
                "min_amount": Decimal("1000001"),
                "max_amount": None,  # 1M and above
                "office_charge": Decimal("40000"),
            },
        ]

        created_count = 0
        for tier_data in tiers:
            tier, created = OfficeChargeTier.objects.get_or_create(
                min_amount=tier_data["min_amount"],
                max_amount=tier_data["max_amount"],
                defaults={"office_charge": tier_data["office_charge"], "is_active": True},
            )
            if created:
                created_count += 1
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Created tier: UGX {tier.min_amount} - {tier.max_amount or 'above'}: UGX {tier.office_charge}"
                    )
                )
            else:
                self.stdout.write(
                    self.style.WARNING(
                        f"Tier already exists: UGX {tier.min_amount} - {tier.max_amount or 'above'}"
                    )
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"\nSuccessfully seeded {created_count} office charge tiers"
            )
        )
