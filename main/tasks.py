from celery import Celery
from main.config import settings
from flask import Flask


def create_celery_app(app: Flask = None) -> Celery:
    celery = Celery(app.import_name if app else __name__, **settings.CELERY_CONFIG)

    if app:

        class ContextTask(celery.Task):
            def __call__(self, *args, **kwargs):
                with app.app_context():
                    return self.run(*args, **kwargs)

        celery.Task = ContextTask
        celery.flask_app = app
        celery.conf.update(app.config)

    # Auto-discover tasks from modules
    celery.autodiscover_tasks(
        [
            "app.socials.tasks",
            "app.notifications.tasks",
            "app.media.tasks",
            "app.realtime.tasks",  # New real-time tasks module
            # add more task modules here
        ]
    )

    # Import and apply beat schedule
    from main.schedules import CELERYBEAT_SCHEDULE

    celery.conf.CELERYBEAT_SCHEDULE = CELERYBEAT_SCHEDULE

    # Explicit task routing
    celery.conf.task_routes = {
        "app.media.tasks.*": {"queue": "media"},
        "app.socials.tasks.*": {"queue": "social"},
        "app.notifications.tasks.*": {"queue": "notifications"},
        "app.realtime.tasks.*": {"queue": "realtime"},  # New real-time queue
    }

    return celery


# celery_app = create_celery_app()
