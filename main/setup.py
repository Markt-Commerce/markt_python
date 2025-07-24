# python imports
import logging
import time

# package imports
from flask import Flask
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_cors import CORS
from flask_smorest import Api
from flask_socketio import SocketIO

# app imports
from main.config import settings
from main.logger import setup_logging
from main.errors import handle_error
from main.middleware import AuthMiddleware
from main.routes import register_blueprints, create_root_routes
from main.sockets import register_socket_namespaces

logger = logging.getLogger(__name__)


def configure_app(app):
    """Configure Flask application"""
    app.config.from_object(settings)

    # Setup extensions
    login_manager = LoginManager(app)
    login_manager.login_view = "users.UserLogin"

    from external.database import db, database

    database.init_app(app)
    Migrate(app, db)
    CORS(app, supports_credentials=True, origins=["*"])

    # Initialize Flask-Smorest API
    api = Api(app)

    from .extensions import socketio

    # Initialize socketio
    socketio.init_app(app, logger=settings.DEBUG, engineio_logger=settings.DEBUG)

    # Register error handler
    app.register_error_handler(Exception, handle_error)

    return login_manager, api, socketio


def create_app():
    """Application factory"""
    setup_logging()

    app = Flask(__name__)
    app.wsgi_app = AuthMiddleware(app.wsgi_app)

    # Track application start time for health checks
    app.start_time = time.time()

    # Get both login_manager and api
    login_manager, api, socketio = configure_app(app)

    with app.app_context():
        from external.database import db

        # db.create_all()

        # Setup user loader
        from app.users.models import User

        @login_manager.user_loader
        def load_user(user_id):
            return User.query.get(str(user_id))

        # Register routes
        register_blueprints(app, api)
        create_root_routes(app)

        # Register socket namespaces
        register_socket_namespaces(socketio)

        # Initialize PaymentService with Paystack keys
        if settings.PAYSTACK_SECRET_KEY and settings.PAYSTACK_PUBLIC_KEY:
            from app.payments.services import PaymentService

            PaymentService.initialize_paystack(
                settings.PAYSTACK_SECRET_KEY, settings.PAYSTACK_PUBLIC_KEY
            )
            logger.info("PaymentService initialized with Paystack keys")
        else:
            logger.warning(
                "Paystack keys not configured - payment features will not work"
            )

    logger.info("Application initialized")
    return app, socketio


def create_flask_app():
    """
    Flask CLI-compatible app factory.

    This function is specifically intended for use with Flask CLI commands like:
        flask db migrate
        flask db upgrade

    Since the main `create_app()` returns a tuple (app, socketio), which is not compatible
    with the Flask CLI (expects a Flask instance), this wrapper returns only the Flask app
    to enable proper integration with tools like Flask-Migrate.
    """
    return create_app()[0]
