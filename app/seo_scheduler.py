def start_seo_generator_scheduler(app):
    """SEO auto generator is intentionally disabled.

    SEO content is now managed manually in /admin/seo.
    This function remains only so older app startup code does not break.
    """
    try:
        app.logger.info('SEO generator scheduler is disabled: manual SEO mode is active.')
    except Exception:
        pass
    return
