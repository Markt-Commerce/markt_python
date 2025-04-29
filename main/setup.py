from flask import Flask
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_cors import CORS
from flask_smorest import Api
from main.config import settings
from main.logger import setup_logging
from main.error import handle_error
from main.middleware import AuthMiddleware
from main.routes import register_blueprints, create_root_routes
import logging

logger = logging.getLogger(__name__)


def configure_app(app):
    """Configure Flask application"""
    app.config.from_object(settings)

    # Setup extensions
    login_manager = LoginManager(app)
    login_manager.login_view = "users.login"

    from external.database import db

    db.init_app(app)
    Migrate(app, db)

    CORS(app)
    # Initialize Flask-Smorest API
    api = Api(app)

    # Register error handler
    app.register_error_handler(Exception, handle_error)

    return login_manager, api


def create_app():
    """Application factory"""
    setup_logging()

    app = Flask(__name__)
    app.wsgi_app = AuthMiddleware(app.wsgi_app)

    # Get both login_manager and api
    login_manager, api = configure_app(app)

    with app.app_context():
        from external.database import db

        # db.create_all()

        # Setup user loader
        from app.users.models import User

        @login_manager.user_loader
        def load_user(user_id):
            return User.query.get(int(user_id))

        # Register routes
        register_blueprints(app, api)
        create_root_routes(app)

    logger.info("Application initialized")
    return app
