import atexit
import os

from apscheduler.schedulers.background import BackgroundScheduler

from .supplier_report_utils import send_supplier_orders_report
from .utils import setting

_scheduler = None


def _int_setting(key, default):
    try:
        return int(setting(key, str(default)) or default)
    except ValueError:
        return default


def start_supplier_report_scheduler(app):
    """Start the daily supplier PDF email scheduler once per Flask process."""
    global _scheduler

    if _scheduler is not None:
        return

    # Prevent duplicate jobs when Flask debug reloader starts the parent process.
    if app.debug and os.environ.get('WERKZEUG_RUN_MAIN') != 'true':
        return

    with app.app_context():
        if setting('supplier_report_enabled', '1') != '1':
            app.logger.info('Supplier report scheduler is disabled by settings.')
            return

        hour = _int_setting('supplier_report_hour', 0)
        minute = _int_setting('supplier_report_minute', 0)
        timezone = setting('supplier_report_timezone', 'Europe/Prague') or 'Europe/Prague'

    scheduler = BackgroundScheduler(timezone=timezone)

    def job():
        with app.app_context():
            result = send_supplier_orders_report()
            if result.get('ok'):
                app.logger.info('Supplier report job result: %s', result)
            else:
                app.logger.error('Supplier report job failed: %s', result)

    scheduler.add_job(
        job,
        trigger='cron',
        hour=hour,
        minute=minute,
        id='daily_supplier_orders_pdf_email',
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    _scheduler = scheduler
    atexit.register(lambda: scheduler.shutdown(wait=False))
