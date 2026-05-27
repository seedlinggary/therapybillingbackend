from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
import logging

from app.config import settings
from app.routers import auth, onboarding, clients, appointments, invoices, stripe_webhooks, payme_webhooks, paypal_webhooks
from app.routers.admin import router as admin_router
from app.routers.accounting import router as accounting_router, docs_router
from app.routers.service_types import router as service_types_router
from app.routers.contact import router as contact_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="PracticeBilling API",
    version="1.0.0",
    description="Scheduling and billing platform for any practice or business",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Routers ─────────────────────────────────────────────────────────────────

app.include_router(auth.router)
app.include_router(onboarding.router)
app.include_router(clients.router)
app.include_router(appointments.router)
app.include_router(invoices.router)
app.include_router(stripe_webhooks.router)
app.include_router(payme_webhooks.router)
app.include_router(paypal_webhooks.router)
app.include_router(admin_router)
app.include_router(accounting_router)
app.include_router(docs_router)
app.include_router(service_types_router)
app.include_router(contact_router)


# ─── Scheduler ───────────────────────────────────────────────────────────────

scheduler = BackgroundScheduler()


@app.on_event("startup")
def seed_admin():
    """Create the superuser account if it doesn't exist yet."""
    from app.database import SessionLocal
    from app.models.admin_user import AdminUser
    from app.core.security import hash_password
    db = SessionLocal()
    try:
        if not db.query(AdminUser).first():
            db.add(AdminUser(
                email="gary.s.schwartz617@gmail.com",
                name="Gary Schwartz",
                hashed_password=hash_password("Garystar617"),
            ))
            db.commit()
            logger.info("Admin user seeded")
    finally:
        db.close()


@app.on_event("startup")
def start_scheduler():
    from app.jobs.daily_billing import run_daily_billing
    from app.jobs.retry_worker import run_retry_worker
    from app.jobs.payment_reminders import run_payment_reminders

    scheduler.add_job(
        run_daily_billing,
        trigger=CronTrigger(hour=2),
        id="daily_billing",
        replace_existing=True,
        misfire_grace_time=3600,
        coalesce=True,
    )
    scheduler.add_job(
        run_payment_reminders,
        trigger=CronTrigger(hour=3),
        id="payment_reminders",
        replace_existing=True,
        misfire_grace_time=3600,
        coalesce=True,
    )
    scheduler.add_job(
        run_retry_worker,
        trigger=IntervalTrigger(minutes=5),
        id="accounting_retry_worker",
        replace_existing=True,
        misfire_grace_time=300,
        coalesce=True,
    )
    scheduler.start()
    logger.info("APScheduler started — daily billing 02:00 UTC, payment reminders 03:00 UTC, retry worker every 5 min")


@app.on_event("shutdown")
def stop_scheduler():
    scheduler.shutdown()


# ─── Health ───────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}


# ─── Manual billing trigger (admin/debug) ────────────────────────────────────

@app.post("/admin/billing/run")
def trigger_billing(target_date: str = None):
    """Manually trigger the daily billing job. Protect with admin auth in production."""
    from app.jobs.daily_billing import run_daily_billing
    from datetime import date
    parsed_date = date.fromisoformat(target_date) if target_date else None
    result = run_daily_billing(target_date=parsed_date)
    return result
