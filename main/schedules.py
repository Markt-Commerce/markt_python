from celery.schedules import crontab
from datetime import timedelta

CELERYBEAT_SCHEDULE = {
    "generate-feeds": {
        "task": "app.socials.tasks.generate_all_feeds",
        "schedule": crontab(hour=1, minute=0),
        "options": {"queue": "social"},
    },
    "update-trending": {
        "task": "app.socials.tasks.update_popular_content",
        "schedule": crontab(minute="*/30"),
        "options": {"queue": "social"},
    },
}
