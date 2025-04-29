from flask import Blueprint
from importlib import import_module
import logging
from main.config import settings

logger = logging.getLogger(__name__)


def register_blueprints(app):
    """Dynamically register all blueprints from app modules"""
    modules = ["users", "products", "orders", "chat"]

    for module in modules:
        try:
            mod = import_module(f"app.{module}.routes")
            bp = getattr(mod, "bp", None) or getattr(mod, f"{module}_bp")
            app.register_blueprint(bp)
            logger.info(f"Registered blueprint for {module}")
        except ImportError as e:
            logger.warning(f"Failed to register {module} routes: {str(e)}")
        except AttributeError:
            logger.warning(f"No blueprint found in {module}.routes")


def create_root_routes(app):
    @app.route("/status")
    def status():
        return {"status": "running", "environment": settings.ENV}
