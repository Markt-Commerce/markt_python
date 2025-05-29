from main.tasks import create_celery_app
from main.setup import create_flask_app


# Create Flask app and Celery with proper context
flask_app = create_flask_app()
celery_app = create_celery_app(flask_app)


if __name__ == "__main__":
    celery_app.start()
