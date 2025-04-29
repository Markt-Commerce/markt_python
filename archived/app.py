from flask import Flask
from flask_smorest import Api
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_mail import Mail
from flask_cors import CORS
from flask_socketio import SocketIO

import app.models

from db import db

socketio = SocketIO()
cors = CORS()
mail = Mail()


def create_app(config_name="development"):
    app = Flask(__name__)
    app.config.from_object(f"config.{config_name.capitalize()}Config")

    # Initialize extensions
    db.init_app(app)
    mail.init_app(app)
    Migrate(app, db)
    api = Api(app)

    # Flask Login for Session based auth
    login_manager = LoginManager(app)
    login_manager.login_view = "auth.UserLogin"
    login_manager.init_app(app)

    # Initialize Flask-SocketIO with CORS
    cors.init_app(app, resources={r"/*": {"origins": "*"}})
    socketio.init_app(
        app, cors_allowed_origins="*"
    )  # Replace with your frontend domain in production

    with app.app_context():
        db.create_all()

        # Import and register blueprints here
        from .auth import auth_blp
        from .routes.cart import cart_bp
        from .routes.comments import comment_bp
        from .routes.favorites import favorite_bp
        from .routes.forgot_password_handler import pswd_retrvl_bp
        from .routes.order import order_bp
        from .routes.product import product_bp
        from .routes.product_request import product_request_bp
        from .routes.user import user_blp
        from .routes.chat import chat_bp  # New chat blueprint

        # Register blueprints
        api.register_blueprint(auth_blp)
        api.register_blueprint(user_blp)
        api.register_blueprint(product_bp)
        api.register_blueprint(pswd_retrvl_bp)
        api.register_blueprint(cart_bp)
        api.register_blueprint(order_bp)
        api.register_blueprint(favorite_bp)
        api.register_blueprint(comment_bp)
        api.register_blueprint(product_request_bp)
        api.register_blueprint(chat_bp)  # Register new chat blueprint

        from app.models import User

        @login_manager.user_loader
        def load_user(user_id):
            return User.query.get(int(user_id))

        return app, socketio
