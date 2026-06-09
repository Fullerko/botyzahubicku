from apscheduler.schedulers.background import BackgroundScheduler

_emailing_scheduler = None


def start_emailing_scheduler(app):
    """Spustí lehký background worker pro hromadné kampaně."""
    global _emailing_scheduler
    if _emailing_scheduler and _emailing_scheduler.running:
        return _emailing_scheduler

    _emailing_scheduler = BackgroundScheduler(timezone='Europe/Prague')

    def run_batch():
        try:
            from .emailing_service import send_campaign_batch
            send_campaign_batch(app)
        except Exception as exc:
            try:
                app.logger.exception('Emailing scheduler failed: %s', exc)
            except Exception:
                print('Emailing scheduler failed:', exc)

    _emailing_scheduler.add_job(
        run_batch,
        'interval',
        seconds=60,
        id='emailing_send_batch',
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    _emailing_scheduler.start()
    return _emailing_scheduler
