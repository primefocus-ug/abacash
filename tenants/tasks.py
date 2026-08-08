"""
Run with the same worker already used for reminders:
  celery -A aba_uganda worker --loglevel=info --pool=eventlet
"""
import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=0)
def provision_tenant_task(self, company_id, domain, email, password=None, plan="STARTER",
                           phone="", address="", company_email="", notify=False):
    """Background counterpart to tenants.provisioning.provision_tenant().

    Deliberately no automatic retries (max_retries=0) — a failed
    provisioning run needs a human to look at provisioning_error before
    trying again (schema creation is not always safely idempotent to just
    blindly re-run), so retry is a manual action from the company detail
    page rather than automatic.
    """
    from .provisioning import provision_tenant, ProvisioningError

    try:
        result = provision_tenant(
            company_id, domain, email, password=password, plan=plan,
            phone=phone, address=address, company_email=company_email,
            notify=notify, log=logger.info,
        )
        logger.info("Provisioning task completed for company_id=%s: %s", company_id, result)
        return result
    except ProvisioningError as exc:
        # Already recorded on the Company row by provision_tenant() itself —
        # just log here so it also shows up in Celery's own task history.
        logger.error("Provisioning task failed for company_id=%s: %s", company_id, exc)
        return {"company_id": company_id, "error": str(exc)}
