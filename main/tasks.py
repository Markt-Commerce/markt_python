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

    # Auto-discover tasks from modules
    celery.autodiscover_tasks(
        [
            "app.socials.tasks",
            # 'app.products.tasks'
        ]
    )

    return celery


celery_app = create_celery_app()
