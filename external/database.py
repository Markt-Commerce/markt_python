from flask_sqlalchemy import SQLAlchemy
from main.config import settings
import logging

logger = logging.getLogger(__name__)

db = SQLAlchemy()


class Database:
    def __init__(self, app=None):
        self.app = app
        if app is not None:
            self.init_app(app)

    def init_app(self, app):
        # Configure SQLAlchemy
        app.config["SQLALCHEMY_DATABASE_URI"] = settings.SQLALCHEMY_DATABASE_URI
        app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
            "pool_size": 20,
            "max_overflow": 30,
            "pool_recycle": 3600,
        }

        db.init_app(app)

        # Import models to ensure they're registered with SQLAlchemy
        # with app.app_context():
        #     from app.users.models import User, Buyer, Seller, UserAddress
        # Import other models as needed


# Create the database instance
database = Database()
