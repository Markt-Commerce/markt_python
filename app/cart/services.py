# python imports
import json
import logging

from sqlalchemy.exc import SQLAlchemyError

# project imports
from external.redis import redis_client
from external.database import db
from app.libs.session import session_scope
from app.products.models import Product
from app.libs.errors import NotFoundError, ValidationError, ConflictError, APIError

# app imports
from .models import Cart, CartItem


logger = logging.getLogger(__name__)


class CartService:
    @staticmethod
    def get_user_cart(buyer_id):
        """Get cart from Redis cache or database"""
        # Try Redis first
        cached_cart = redis_client.client.get(f"cart:{buyer_id}")
        if cached_cart:
            return json.loads(cached_cart)

        # Fallback to database
        with session_scope() as session:
            cart = session.query(Cart).filter_by(buyer_id=buyer_id).first()
            if not cart:
                cart = Cart(buyer_id=buyer_id)
                session.add(cart)
                session.commit()

            cart_data = {
                "id": cart.id,
                "items": [
                    {
                        "product_id": item.product_id,
                        "variant_id": item.variant_id,
                        "quantity": item.quantity,
                        "price": item.product_price,
                    }
                    for item in cart.items
                ],
                "subtotal": cart.subtotal(),
            }

            # Cache in Redis
            redis_client.cache_cart(buyer_id, json.dumps(cart_data))
            return cart_data

    @staticmethod
    def add_to_cart(buyer_id, product_id, quantity=1, variant_id=None):
        try:
            if quantity <= 0:
                raise ValidationError("Quantity must be positive")

            with session_scope() as session:
                # Get or create cart
                cart = session.query(Cart).filter_by(buyer_id=buyer_id).first()
                if not cart:
                    cart = Cart(buyer_id=buyer_id)
                    session.add(cart)
                    session.flush()

                # Get product price
                product = session.query(Product).get(product_id)
                if not product:
                    raise NotFoundError("Product not found")
                if product.status != Product.Status.ACTIVE:
                    raise ConflictError("Product is not available")

                # Add or update item
                existing_item = next(
                    (
                        item
                        for item in cart.items
                        if item.product_id == product_id
                        and item.variant_id == variant_id
                    ),
                    None,
                )

                if existing_item:
                    existing_item.quantity += quantity
                else:
                    new_item = CartItem(
                        cart_id=cart.id,
                        product_id=product_id,
                        variant_id=variant_id,
                        quantity=quantity,
                        product_price=product.price,
                    )
                    session.add(new_item)
                    # Explicitly add to cart's items collection
                    cart.items.append(new_item)

                # Commit changes to ensure items are persisted
                session.commit()

                # Update cache
                cart_data = {
                    "id": cart.id,
                    "items": [
                        {
                            "product_id": item.product_id,
                            "variant_id": item.variant_id,
                            "quantity": item.quantity,
                            "price": item.product_price,
                        }
                        for item in cart.items
                    ],
                    "subtotal": cart.subtotal(),
                }
                redis_client.cache_cart(buyer_id, json.dumps(cart_data))

                return cart_data
        except SQLAlchemyError as e:
            logger.error(f"Database error adding to cart: {str(e)}")
            raise APIError("Failed to update cart", 500)

    # TODO: Add cart merging (guest -> user)
    # TODO: Add promotional calculations
