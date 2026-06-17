import atexit
import os

from apscheduler.schedulers.background import BackgroundScheduler

from .seo_generator import generate_daily_seo_content
from .utils import setting

_scheduler = None


def _int_setting(key, default):
    try:
        return int(setting(key, str(default)) or default)
    except Exception:
        return default


def start_seo_generator_scheduler(app):
    """Daily SEO draft generator. It is disabled unless seo_generator_enabled=1."""
    global _scheduler
    if _scheduler is not None:
        return

    if app.debug and os.environ.get('WERKZEUG_RUN_MAIN') != 'true':
        return

    with app.app_context():
        if setting('seo_generator_enabled', '0') != '1':
            app.logger.info('SEO generator scheduler is disabled by settings.')
            return
        hour = _int_setting('seo_generator_hour', 6)
        minute = _int_setting('seo_generator_minute', 0)
        timezone = setting('seo_generator_timezone', 'Europe/Prague') or 'Europe/Prague'

    scheduler = BackgroundScheduler(timezone=timezone)

    def job():
        with app.app_context():
            result = generate_daily_seo_content(
                blog_count=_int_setting('seo_generate_blogs_per_day', 10),
                landing_count=_int_setting('seo_generate_categories_per_day', 10),
                auto_publish=(setting('seo_auto_publish', '0') == '1'),
            )
            app.logger.info('SEO generator job result: %s', result)

    scheduler.add_job(
        job,
        trigger='cron',
        hour=hour,
        minute=minute,
        id='daily_seo_content_generator',
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    _scheduler = scheduler
    atexit.register(lambda: scheduler.shutdown(wait=False))
