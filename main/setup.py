# python imports
import logging
import time

# package imports
from flask import Flask
from flask_login import LoginManager
from werkzeug.middleware.proxy_fix import ProxyFix
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

    # Since we are having two points of auth entry now, would we need this? @Adebowale-Morakinyo
    login_manager.login_view = "users.UserLogin"

    # API-friendly unauthorized response (avoid redirects to GET /users/login)
    @login_manager.unauthorized_handler
    def _unauthorized():
        from flask import jsonify

        return jsonify({"message": "Unauthorized"}), 401

    from external.database import db, database

    database.init_app(app)
    Migrate(app, db)
    CORS(app, supports_credentials=True, origins=settings.ALLOWED_ORIGINS)

    # Initialize Flask-Smorest API
    api = Api(app)

    from .extensions import socketio

    # Initialize socketio
    socketio.init_app(
        app,
        logger=settings.DEBUG,
        engineio_logger=settings.DEBUG,
        cors_allowed_origins=settings.ALLOWED_ORIGINS,
    )

    # Register error handler
    app.register_error_handler(Exception, handle_error)

    return login_manager, api, socketio


def create_app():
    """Application factory"""
    setup_logging()

    app = Flask(__name__)

    # Serve /path and /path/ alike instead of 308-redirecting between them.
    # The redirect was the source of the mobile "empty categories" bug: werkzeug
    # rebuilt the URL with the scheme it saw behind the proxy (http), and
    # release Android builds refuse cleartext, so the request silently died.
    app.url_map.strict_slashes = False

    app.wsgi_app = AuthMiddleware(app.wsgi_app)
    # Trust the reverse proxy's X-Forwarded-* headers so any URL werkzeug does
    # generate (redirects, url_for with _external) keeps https and the real host.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

    # Track application start time for health checks
    app.start_time = time.time()

    # Get both login_manager and api
    login_manager, api, socketio = configure_app(app)

    with app.app_context():
        from external.database import db

        # db.create_all()

        # Setup user loader
        from app.users.models import User
        from app.deliveries.models import DeliveryUser

        @login_manager.user_loader
        def load_user(user_id):
            user = User.query.get(user_id)
            if user:
                # A deleted account keeps its row so other people's posts,
                # reviews and order history stay coherent, but it must never
                # authenticate again (see AccountDeletionService).
                return None if user.deleted_at else user

            delivery_user = DeliveryUser.query.get(user_id)
            if delivery_user:
                return delivery_user

            return None

        @login_manager.request_loader
        def load_user_from_token(req):
            """Authenticate API clients that send a signed bearer token instead
            of a session cookie (the React Native app). Falls back to None so
            Flask-Login can still try the session cookie."""
            auth_header = req.headers.get("Authorization", "")
            if not auth_header.startswith("Bearer "):
                return None

            # Split off the "Bearer " prefix without a slice (avoids black's
            # "whitespace before ':'" which flake8 flags as E203).
            token = auth_header.split(" ", 1)[1].strip()
            if not token:
                return None

            from app.libs.auth_tokens import verify_auth_token

            user_id = verify_auth_token(token)
            if not user_id:
                return None

            user = User.query.get(user_id)
            if user:
                # Bearer tokens are stateless signed user ids with a 30-day
                # life, so this is the only thing that stops a token issued
                # before deletion from continuing to work.
                return None if user.deleted_at else user
            return DeliveryUser.query.get(user_id)

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
    app = create_app()[0]

    # Register custom CLI commands
    from app.categories.management.commands.populate_categories import (
        populate_categories,
    )
    from app.categories.management.commands.list_categories import list_categories
    from app.categories.management.commands.clear_categories import clear_categories

    app.cli.add_command(populate_categories)
    app.cli.add_command(list_categories)
    app.cli.add_command(clear_categories)

    return app
