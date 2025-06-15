from celery.schedules import crontab

CELERYBEAT_SCHEDULE = {
    "generate-feeds": {
        "task": "app.socials.tasks.generate_all_feeds",
        "schedule": crontab(hour=1, minute=0),  # Daily at 1 AM
        "options": {"queue": "social"},
    },
    "update-trending": {
        "task": "app.socials.tasks.update_popular_content",
        "schedule": crontab(minute="*/30"),
        "options": {"queue": "social"},
    },
    "cleanup-old-notifications": {
        "task": "app.notifications.tasks.cleanup_old_notifications",
        "schedule": crontab(hour=2, minute=0),  # Daily at 2 AM
        "options": {"queue": "default"},
    },
}
