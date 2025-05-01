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

        # Import models to ensure they're registered with SQLAlchemy -> Migration
        with app.app_context():
            from app.users.models import User, Buyer, Seller, UserAddress
            from app.products.models import Product, ProductVariant, ProductInventory
            from app.categories.models import Category, ProductCategory, Tag, ProductTag
            from app.orders.models import Order, Shipment
            from app.payments.models import Payment, Transaction
            from app.socials.models import (
                ProductLike,
                ProductComment,
                ProductView,
                Follow,
                Notification,
            )
            from app.requests.models import BuyerRequest, SellerOffer, RequestImage
            from app.media.models import Media, MediaVariant, ProductImage
            from app.chats.models import ChatRoom, ChatMessage, ChatOffer
            from app.cart.models import Cart, CartItem

        # Import other models as needed


# Create the database instance
database = Database()
