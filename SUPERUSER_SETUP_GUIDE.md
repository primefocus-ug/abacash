# Creating Superuser & Checking Tenant - Complete Guide

## Step 1: Activate Your Virtual Environment

Open **PowerShell** in your project directory and run:

```powershell
cd C:\Users\aggyd\Desktop\tenant
.\venv\Scripts\Activate.ps1
```

You should see `(venv)` appear at the beginning of your terminal prompt.

---

## Step 2: Check Existing Tenants

First, let's see what tenants already exist:

```powershell
python manage.py shell
```

This opens the Django interactive shell. Inside it, run:

```python
from tenants.models import Company
for company in Company.objects.all():
    print(f"Schema: {company.schema_name} | Name: {company.name}")
exit()
```

**Example output:**
```
Schema: public | Name: Abacash Public Schema
Schema: sacco_kampala | Name: Sacco Kampala MFI
```

---

## Step 3: Option A - Create a NEW Tenant (Recommended for Testing)

Use the `onboard_tenant` command to create a complete tenant with schema, migrations, and initial CEO user:

```powershell
python manage.py onboard_tenant `
    --schema=test_tenant `
    --name="Test Tenant Company" `
    --domain=test.localhost `
    --email=admin@test-tenant.com `
    --password=TestPassword123! `
    --plan=STARTER `
    --notify
```

**What this does:**
1. ✓ Creates a new Company record
2. ✓ Auto-creates isolated database schema `test_tenant`
3. ✓ Runs all Django migrations in the new schema
4. ✓ Seeds default loan products
5. ✓ Creates initial CEO user (admin@test-tenant.com)
6. ✓ Sends password-reset email (if SMTP configured)

**You should see output like:**
```
Successfully provisioned tenant: test_tenant
CEO user: admin@test-tenant.com
Schema: test_tenant
```

---

## Step 4: Option B - Create Superuser for EXISTING Tenant

If you want to add another admin to an existing tenant:

```powershell
python manage.py create_tenant_superuser
```

**Interactive prompts:**
1. Lists all available tenants
2. Ask: Enter schema name: `test_tenant`
3. Ask: Enter email address: `superadmin@test-tenant.com`
4. Ask: Enter password: (enter password - **not shown**)
5. Ask: Confirm password: (repeat password)

**Example full run:**
```
============================================================
Available tenants:
============================================================
  • public               | Abacash Public Schema
  • test_tenant          | Test Tenant Company
  • sacco_kampala        | Sacco Kampala MFI

Enter schema name: test_tenant
Enter email address: superadmin@test-tenant.com
Enter password:
Confirm password:

✓ Superuser created successfully!

Login credentials:
  Email/Username: superadmin@test-tenant.com
  Schema: test_tenant

Login at: http://localhost:8000/admin/ (if using public admin)
         or access Test Tenant Company schema directly
```

---

## Step 5: Verify Superuser Was Created

Check if the superuser exists in the tenant:

```powershell
python manage.py shell
```

Then inside Python:

```python
from django_tenants.utils import schema_context
from django.contrib.auth import get_user_model
from tenants.models import Company

schema = "test_tenant"  # Use your schema name
company = Company.objects.get(schema_name=schema)

with schema_context(schema):
    User = get_user_model()
    superusers = User.objects.filter(is_superuser=True)
    for user in superusers:
        print(f"  • {user.email} (username: {user.username}) - is_active: {user.is_active}")

exit()
```

**Expected output:**
```
  • superadmin@test-tenant.com (username: superadmin) - is_active: True
  • admin@test-tenant.com (username: admin) - is_active: True
```

---

## Step 6: Inspect Tenant Database Schema

See what tables were created in your tenant:

```powershell
python manage.py dbshell
```

This opens PostgreSQL prompt. Run:

```sql
-- List all tables in tenant schema
SELECT table_name 
FROM information_schema.tables 
WHERE table_schema = 'test_tenant' 
ORDER BY table_name;

-- Check user count in tenant
SELECT COUNT(*) as total_users FROM test_tenant.accounts_user;

-- List all users in tenant
SELECT id, username, email, is_superuser, is_staff 
FROM test_tenant.accounts_user;

-- Exit
\q
```

**Example output:**
```
                    table_name                    
─────────────────────────────────────────────────
 accounts_user
 accounts_userprofile
 accounts_role
 auth_group
 auth_group_permissions
 auth_permission
 auth_user_groups
 auth_user_user_permissions
 clients_client
 clients_account
 loans_loanproduct
 loans_loan
 loans_schedule
 ... (many more)
```

---

## Step 7: Login and Test Access

### Via Admin Interface

1. Open browser: `http://localhost:8000/admin/`
2. **Username**: `superadmin@test-tenant.com` (or `superadmin` if that's the username)
3. **Password**: (what you set above)

**What you should see:**
- Django admin dashboard
- Tables from the tenant schema (Clients, Loans, Products, etc.)
- NOT public schema tables

### Via Tenant Front-end

If you have a tenant front-end application (usually at a specific domain):

1. Open browser: `http://test.localhost:8000/`
2. **Email/Username**: `superadmin@test-tenant.com`
3. **Password**: (what you set)

---

## Step 8: Common Issues & Troubleshooting

### ❌ "relation 'django_session' does not exist"
**Solution**: Ensure migrations ran. Run:
```powershell
python manage.py migrate_schemas --schema=test_tenant
```

### ❌ "User with email already exists"
**Solution**: Delete the old user or use a different email:
```powershell
python manage.py shell
```
Then:
```python
from django_tenants.utils import schema_context
from django.contrib.auth import get_user_model
from tenants.models import Company

schema = "test_tenant"
with schema_context(schema):
    User = get_user_model()
    user = User.objects.get(email="admin@test-tenant.com")
    user.delete()
    print("User deleted")
exit()
```

### ❌ "Schema does not exist"
**Solution**: Create the tenant first using `onboard_tenant` command (Step 3)

### ❌ "SMTP not configured"
**Solution**: Email will fail silently if SMTP not set. Configure in `.env`:
```
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=true
EMAIL_HOST_USER=your-email@gmail.com
EMAIL_HOST_PASSWORD=your-app-password
DEFAULT_FROM_EMAIL=noreply@abacash.com
```

---

## Step 9: Quick Reference Commands

```powershell
# Activate venv
.\venv\Scripts\Activate.ps1

# List all tenants
python manage.py shell -c "from tenants.models import Company; [print(f'{c.schema_name}: {c.name}') for c in Company.objects.all()]"

# Create new tenant (full provisioning)
python manage.py onboard_tenant --schema=test_tenant --name="Test" --domain=test.localhost --email=admin@test.com --password=Pass123! --notify

# Create superuser in existing tenant
python manage.py create_tenant_superuser

# Check migrations status
python manage.py showmigrations --schema=test_tenant

# View Django logs
tail -f logs/onboarding.log

# Run tests
python manage.py test
```

---

## Summary Checklist

- [ ] Virtual environment activated (`(venv)` in terminal)
- [ ] Tenant created with `onboard_tenant` or already exists
- [ ] Superuser created with `create_tenant_superuser`
- [ ] Verified superuser exists in tenant schema
- [ ] Tables created in tenant schema
- [ ] Can login to admin at `http://localhost:8000/admin/`
- [ ] Email notifications working (optional, requires SMTP)

You're now ready to test your tenant system! 🚀
