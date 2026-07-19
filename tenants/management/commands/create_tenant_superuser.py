"""
Management command to create a superuser in a specific tenant schema.

Usage:
  python manage.py create_tenant_superuser --schema=public --email=admin@localhost --password=admin123
  python manage.py create_tenant_superuser  # Interactive mode
"""
import os
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from django.db import connection
from django_tenants.utils import schema_context
from tenants.models import Company

User = get_user_model()


class Command(BaseCommand):
    help = 'Create a superuser in a specific tenant schema'

    def add_arguments(self, parser):
        parser.add_argument(
            '--schema',
            type=str,
            help='Schema name (tenant schema_name)',
        )
        parser.add_argument(
            '--email',
            type=str,
            help='Email address for the superuser',
        )
        parser.add_argument(
            '--password',
            type=str,
            help='Password for the superuser',
        )
        parser.add_argument(
            '--first-name',
            type=str,
            default='Admin',
            help='First name of superuser (default: Admin)',
        )
        parser.add_argument(
            '--last-name',
            type=str,
            default='User',
            help='Last name of superuser (default: User)',
        )

    def handle(self, *args, **options):
        schema = options.get('schema')
        email = options.get('email')
        password = options.get('password')
        first_name = options.get('first_name', 'Admin')
        last_name = options.get('last_name', 'User')

        # Interactive mode if not all args provided
        if not schema:
            self.stdout.write('\n' + '='*60)
            self.stdout.write('Available tenants:')
            self.stdout.write('='*60)
            try:
                for company in Company.objects.all():
                    self.stdout.write(f'  • {company.schema_name:20} | {company.name}')
            except Exception as e:
                self.stdout.write(self.style.WARNING(f'Could not list tenants: {e}'))
                self.stdout.write(self.style.WARNING('Ensure you have a valid database connection.'))

            schema = input('\nEnter schema name: ').strip()

        if not email:
            email = input('Enter email address: ').strip()

        if not password:
            from getpass import getpass
            password = getpass('Enter password: ')
            password_confirm = getpass('Confirm password: ')
            if password != password_confirm:
                raise CommandError('Passwords do not match.')

        # Validate schema exists
        try:
            company = Company.objects.get(schema_name=schema)
        except Company.DoesNotExist:
            raise CommandError(f'Schema "{schema}" not found. Check available tenants above.')

        # Set tenant context using schema_context
        try:
            with schema_context(schema):
                # Check if user already exists
                if User.objects.filter(email=email).exists():
                    response = input(f'\nUser with email "{email}" already exists. Replace? [y/N]: ').strip()
                    if response.lower() != 'y':
                        self.stdout.write(self.style.WARNING('Aborted.'))
                        return
                    User.objects.filter(email=email).delete()

                # Create superuser
                user = User.objects.create_superuser(
                    username=email.split('@')[0],  # Use email prefix as username
                    email=email,
                    password=password,
                    first_name=first_name,
                    last_name=last_name,
                )

                self.stdout.write(self.style.SUCCESS('✓ Superuser created successfully!'))
                self.stdout.write('\nLogin credentials:')
                self.stdout.write(f'  Email/Username: {user.email}')
                self.stdout.write(f'  Schema: {schema}')
                self.stdout.write(f'\nLogin at: http://localhost:8000/admin/ (if using public admin)')
                self.stdout.write(f'         or access {company.name} schema directly')

        except Exception as e:
            raise CommandError(f'Error creating superuser: {str(e)}')
