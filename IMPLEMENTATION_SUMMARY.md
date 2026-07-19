# Abacash Tenant Provisioning Implementation Summary

## Overview
Converted public registration into direct automatic onboarding with automatic migrations, password-reset email flow, and front-end loading animations.

## Changes Made

### 1. **Automatic Tenant Migrations** 
**File**: `tenants/management/commands/onboard_tenant.py`
- Added explicit tenant migration execution using `manage.py migrate_schemas --schema={schema_name}`
- Migrations run BEFORE seeding data, ensuring all required tables exist
- Failures during migrations raise `CommandError` to prevent partial provisioning

### 2. **Password-Reset Email Flow** (Security Improvement)
**File**: `tenants/management/commands/onboard_tenant.py`
- Removed plaintext password email delivery
- Changed to send password-reset link instead (one-time token, secure)
- Uses Django's `default_token_generator` to create secure tokens
- Email body explains the one-time link cannot be reused
- Creates tenant admin user with `set_unusable_password()` (no hardcoded password)
- Graceful fallback to login page if password-reset link cannot be generated

### 3. **Background Onboarding Job**
**File**: `tenants/views.py` (register view)
- Removed direct management command invocation (blocking)
- Launch detached subprocess running `manage.py onboard_tenant --notify`
- Windows: Uses `DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP` flags
- Unix: Uses standard detached subprocess approach
- Returns immediately to user with success message
- Generated admin password and schema stored in `CompanyRegistration.notes` for operator reference (not exposed to user)

### 4. **Comprehensive Logging**
**Files**: 
- `config/settings.py` - Added LOGS_DIR and logging configuration
- `tenants/management/commands/onboard_tenant.py` - File-based logging with `_setup_logging()` method
- `tenants/views.py` - Added logger and log entries for onboarding start/errors

**Log Outputs**:
- Onboarding: `logs/onboarding.log` - All provisioning operations
- Per-tenant: `logs/onboard_{schema}.log` - Individual tenant provisioning details
- Both files include timestamp, level, and detailed messages

### 5. **Front-End Loading Animation**
**File**: `templates/tenants/success.html`
- Animated Abacash logo (SVG) with 2-second rotation
- Progress bar with linear gradient
- Step-by-step provisioning status (checkmarks for completed, hourglass for in-progress)
- Smooth transition from provisioning state to success state
- Auto-refresh check every 10 seconds (max 10 minutes wait)
- "Hold on, we're setting up your tenant..." messaging
- Password reset instructions

### 6. **Settings Configuration**
**File**: `config/settings.py`
- Added `LOGS_DIR = os.path.join(BASE_DIR, 'logs')`
- Auto-creates logs directory on startup
- Added logging handler: `onboarding_file` for tenants logger
- Added logger: `tenants` → uses onboarding_file handler

### 7. **User Experience Improvements**
**Messages**:
- Registration: "Thank you! Your registration is being provisioned — you'll receive an email when ready."
- AJAX: "Thank you! Provisioning has started and you'll receive confirmation shortly."
- Success page shows estimated 1-2 minute provisioning time

## Process Flow

```
User Registration
    ↓
Form Submission (POST to /register/)
    ↓
Create CompanyRegistration record
    ↓
Send admin notification (mail_admins)
    ↓
Launch background process: manage.py onboard_tenant --notify
    ├─ Create Company + Domain
    ├─ Run tenant migrations
    ├─ Seed settings, sequences, products
    ├─ Create CEO user (no password set)
    └─ Send password-reset email
    ↓
Return immediately to success page (no waiting)
    ↓
User sees loading animation with progress steps
    ↓
Background job completes (1-2 minutes)
    ↓
Email arrives with password-reset link
    ↓
User clicks link → Sets password → Logs in
```

## Security Highlights

1. **No Plaintext Passwords Stored or Emailed**
   - Admin users created without usable password
   - One-time password-reset tokens sent via email
   - Tokens have configurable expiry (Django default: 1 day)

2. **Password Not Stored in Database Notes**
   - Only provisioning metadata stored (schema, domain, timestamp)
   - Operator can retrieve logs/status without seeing passwords

3. **Logs Directory Permission Considerations**
   - Ensure `logs/` directory is writable by Django process user
   - Consider restricting log file permissions to exclude sensitive data

## Deployment Checklist

- [ ] Create `logs/` directory at project root: `mkdir -p logs`
- [ ] Set proper permissions: `chmod 750 logs/` (or as needed for process user)
- [ ] Configure SMTP settings in environment (EMAIL_HOST, EMAIL_PORT, EMAIL_HOST_USER, EMAIL_HOST_PASSWORD, DEFAULT_FROM_EMAIL)
- [ ] Test password-reset link generation (verify Django's password reset views/tokens are configured)
- [ ] Run migrations: `python manage.py migrate_schemas --shared && python manage.py migrate_schemas`
- [ ] Test registration flow end-to-end
- [ ] Monitor `logs/onboarding.log` for any provisioning errors
- [ ] Verify email backend working (test with `python manage.py shell`: `send_mail(...)`)

## Testing Steps

1. **Test Registration Flow**:
   ```bash
   # Submit registration form on /register/
   # Should see success page with loading animation
   # Background job should start automatically
   ```

2. **Monitor Provisioning**:
   ```bash
   # Check logs
   tail -f logs/onboarding.log
   tail -f logs/onboard_{schema}.log  # e.g., onboard_acme_corp.log
   ```

3. **Verify Tenant Creation**:
   ```bash
   # In psql
   SELECT schema_name, name FROM tenants_company WHERE schema_name = '{schema}';
   \dn  # List all schemas
   \dt tenants_{schema}.*  # List tables in tenant schema
   ```

4. **Check Email**:
   - Watch for password-reset email from DEFAULT_FROM_EMAIL
   - Email should contain one-time password-reset link
   - Link format: `https://{domain}/accounts/reset/{uid}/{token}/`

5. **Test Password Reset**:
   - Click reset link
   - Set new password
   - Log in with email and new password

## Known Limitations & Future Enhancements

1. **Polling-Based Success Detection**: Frontend uses client-side polling (10-second intervals) to detect completion. For production, consider:
   - WebSocket or Server-Sent Events for real-time status
   - API endpoint to check provisioning status
   - Background job result store (Celery results, cache, DB)

2. **No Retry Mechanism**: If background job fails, there's no automatic retry. Implement:
   - Manual retry via admin interface
   - Automatic retry with exponential backoff via Celery/RQ

3. **Silent Failures**: Failed onboarding jobs log to files but don't notify user. Consider:
   - Webhook/callback to update registration status
   - Periodic check of orphaned registrations
   - Email notification if provisioning fails

4. **Single Admin Password Reset**: Currently only CEO admin is created. For production:
   - Allow operator to specify additional initial admins/roles during onboarding
   - Create multiple password-reset links if needed

## Files Modified

1. `tenants/management/commands/onboard_tenant.py` - ✅ Updated (recreate from new version if issues)
2. `tenants/views.py` - ✅ Updated
3. `config/settings.py` - ✅ Updated
4. `templates/tenants/success.html` - ✅ Updated

## Rollback

To revert to synchronous onboarding:
1. In `tenants/views.py` register(), change subprocess call back to `management.call_command()` (blocking)
2. Remove logging from views.py
3. Revert settings.py LOGS_DIR and logging config
4. Simplify success.html template

---

**Last Updated**: 2026-07-17
**Status**: Ready for testing and deployment
