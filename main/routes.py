from flask import Blueprint
from importlib import import_module
import logging
from main.config import settings

logger = logging.getLogger(__name__)


def register_blueprints(app, api):
    """Dynamically register all blueprints from app modules"""
    modules = [
        "users",
        "products",
        "search",
        "orders",
        "chats",
        "cart",
        "requests",
        "media",
        "categories",
        "socials",
        "deliveries",
        "payments",
        "notifications",
        "health",
        "wallet",
        "gamification",
        "fulfilment",
        "metrics",
        "markets",
        "moderation",
    ]

    for module in modules:
        try:
            mod = import_module(f"app.{module}.routes")
            bp = getattr(mod, "bp", None) or getattr(mod, f"{module}_bp")

            # Add URL prefix to each blueprint (idempotent across app factory calls)
            prefix = bp.url_prefix or ""
            if not prefix.startswith("/api/v1"):
                bp.url_prefix = f"/api/v1{prefix}"

            api.register_blueprint(bp)
            logger.info(f"Registered blueprint for {module} at {bp.url_prefix}")
        except ImportError as e:
            logger.warning(f"Failed to register {module} routes: {str(e)}")
        except AttributeError as e:
            logger.warning(f"No blueprint found in {module}.routes: {str(e)}")


def create_root_routes(app):
    # Update status endpoint to include version
    @app.route("/api/v1/status")
    def status():
        return {"status": "running", "environment": settings.ENV, "version": "v1"}
