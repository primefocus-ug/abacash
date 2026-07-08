from django.core.management.base import BaseCommand
from decimal import Decimal
from datetime import date, timedelta
import random

from django.db import connection
from django_tenants.management.commands import InteractiveTenantOption

from clients.models import Client
from loans.models import Loan, LoanProduct
from loans.utils import generate_schedule


FIRST_NAMES = [
    'James','Grace','Daniel','Aisha','John','Mary','Kevin','Ruth','Paul','Esther',
    'Michael','Sarah','Peter','Lilian','David','Naomi','Mark','Helen','Robert','Joy'
]

LAST_NAMES = [
    'Kato','Nakamura','Owino','Amooti','Mwebesa','Okello','Kisakye','Nakato','Sserunjogi','Kajubi',
    'Nakazibwe','Byaruhanga','Muwanguzi','Tumusiime','Kabyanga','Lubega','Katende','Mirembe','Balikuddembe','Namugga'
]


class Command(InteractiveTenantOption, BaseCommand):
    help = (
        'Generate sample clients and loans for development (approx 20). '
        'Runs against a single tenant schema, e.g.: '
        './manage.py generate_sample_data --schema=acme'
    )

    def handle(self, *args, **options):
        tenant = self.get_tenant_from_options_or_interactive(**options)
        connection.set_tenant(tenant)
        self.stdout.write(f'Running against tenant schema "{tenant.schema_name}"...')

        created_clients = []

        # Ensure there's at least one loan product
        product = LoanProduct.objects.first()
        if not product:
            product = LoanProduct.objects.create(
                name='Sample Loan',
                interest_rate_monthly=Decimal('2.50'),
                interest_method=LoanProduct.InterestMethod.FLAT_RATE,
                min_amount=Decimal('100000'),
                max_amount=Decimal('2000000'),
                min_term_months=1,
                max_term_months=12,
                penalty_rate_monthly=Decimal('2.00'),
                processing_fee_percent=Decimal('1.00'),
                requires_guarantor=False,
                is_active=True,
            )

        # Create ~20 clients
        for i in range(20):
            fn = FIRST_NAMES[i % len(FIRST_NAMES)] + (str(i//len(FIRST_NAMES)) if i>=len(FIRST_NAMES) else '')
            ln = LAST_NAMES[i % len(LAST_NAMES)]
            nin = f"NIN{i:06d}"
            phone = f"+2567{random.randint(10000000,99999999)}"
            dob = date(1985 + (i % 10), 1 + ((i % 11) % 12), 1 + (i % 27))

            client = Client.objects.create(
                first_name=fn,
                last_name=ln,
                other_names='',
                gender='M',
                date_of_birth=dob,
                marital_status='SINGLE',
                nin=nin,
                phone_primary=phone,
                physical_address='Sample address, Kampala',
                district='Kampala',
                employment_status='EMPLOYED',
                monthly_income=Decimal(str(random.randint(1000000,5000000))),
            )
            created_clients.append(client)

        # Create one loan per client
        for client in created_clients:
            principal = Decimal(str(random.randint(150000, 1500000)))
            term_months = random.randint(1, 6)
            frequency = random.choice(['MONTHLY', 'WEEKLY'])
            # generate schedule to compute totals
            schedule, totals = generate_schedule(
                principal=principal,
                annual_rate=product.interest_rate_monthly * Decimal('12'),
                term_months=term_months,
                start_date=date.today(),
                method=product.interest_method,
                frequency=frequency,
            )

            loan = Loan.objects.create(
                client=client,
                product=product,
                principal_amount=principal,
                interest_rate_monthly=product.interest_rate_monthly,
                interest_method=product.interest_method,
                penalty_rate_monthly=product.penalty_rate_monthly,
                term_months=term_months,
                repayment_frequency=frequency,
                total_repayable=totals['total_repayable'],
                total_interest=totals['total_interest'],
                outstanding_balance=totals['total_repayable'],
                status=Loan.Status.ACTIVE,
                application_date=date.today(),
                disbursement_date=date.today(),
                first_repayment_date=schedule[0]['due_date'] if schedule else None,
            )

        self.stdout.write(self.style.SUCCESS(
            'Created %d clients and %d loans in tenant "%s"'
            % (len(created_clients), len(created_clients), tenant.schema_name)
        ))