# python imports
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import joinedload

# project imports
from external.redis import redis_client
from external.database import db
from app.libs.session import session_scope
from app.products.models import Product
from app.libs.errors import (
    NotFoundError,
    ValidationError,
    ConflictError,
    APIError,
    ForbiddenError,
)

# app imports
from .models import Cart, CartItem
from app.users.models import User, Buyer
from app.products.models import ProductStatus
from app.orders.models import Order, OrderItem, OrderStatus
from app.notifications.services import NotificationService
from app.notifications.models import NotificationType

logger = logging.getLogger(__name__)


class CartService:
    """Service for managing shopping carts with Redis caching and dual-role validation"""

    # Cache configuration
    CACHE_EXPIRY = 3600  # 1 hour
    CART_CACHE_KEY = "cart:{buyer_id}"

    @staticmethod
    def get_or_create_cart(user_id: str) -> Cart:
        """Get existing cart or create new one for user"""
        with session_scope() as session:
            # Validate user has buyer account
            user = session.query(User).get(user_id)
            if not user or not user.is_buyer:
                raise ForbiddenError("Only buyers can have shopping carts")

            # Try to get existing active cart
            cart = (
                session.query(Cart)
                .filter_by(buyer_id=user.buyer_account.id)
                .filter(Cart.expires_at > datetime.utcnow())
                .options(joinedload("items").joinedload("product"))
                .first()
            )

            if not cart:
                # Create new cart
                cart = Cart()
                cart.buyer_id = user.buyer_account.id
                cart.expires_at = datetime.utcnow() + timedelta(days=30)
                session.add(cart)
                session.flush()

                # Cache the new cart
                CartService._cache_cart(cart)

            return cart

    @staticmethod
    def add_to_cart(
        user_id: str,
        product_id: str,
        quantity: int = 1,
        variant_id: Optional[int] = None,
    ) -> CartItem:
        """Add product to cart with validation and caching"""
        with session_scope() as session:
            # Validate user and get cart
            user = session.query(User).get(user_id)
            if not user or not user.is_buyer:
                raise ForbiddenError("Only buyers can add items to cart")

            cart = CartService.get_or_create_cart(user_id)

            # Validate product
            product = session.query(Product).get(product_id)
            if not product:
                raise NotFoundError("Product not found")

            if product.status != ProductStatus.ACTIVE:
                raise ValidationError("Product is not available for purchase")

            # Validate variant if provided
            if variant_id:
                # TODO: Import ProductVariant when available
                # variant = session.query(ProductVariant).get(variant_id)
                # if not variant or variant.product_id != product_id:
                #     raise ValidationError("Invalid product variant")
                pass

            # Check if item already exists in cart
            existing_item = (
                session.query(CartItem)
                .filter_by(
                    cart_id=cart.id, product_id=product_id, variant_id=variant_id
                )
                .first()
            )

            if existing_item:
                # Update quantity
                existing_item.quantity += quantity
                cart_item = existing_item
            else:
                # Create new cart item
                cart_item = CartItem()
                cart_item.cart_id = cart.id
                cart_item.product_id = product_id
                cart_item.variant_id = variant_id
                cart_item.quantity = quantity
                cart_item.product_price = product.price
                session.add(cart_item)

            session.flush()

            # Update cache
            CartService._cache_cart(cart)

            # Notify seller about cart addition (optional)
            CartService._notify_seller_cart_addition(
                product.seller_id, product_id, quantity
            )

            return cart_item

    @staticmethod
    def update_cart_item(
        user_id: str, item_id: int, quantity: int
    ) -> Optional[CartItem]:
        """Update cart item quantity"""
        with session_scope() as session:
            # Validate user
            user = session.query(User).get(user_id)
            if not user or not user.is_buyer:
                raise ForbiddenError("Only buyers can update cart items")

            # Get cart item
            cart_item = (
                session.query(CartItem)
                .join(Cart)
                .filter(CartItem.id == item_id, Cart.buyer_id == user.buyer_account.id)
                .first()
            )

            if not cart_item:
                raise NotFoundError("Cart item not found")

            if quantity <= 0:
                # Remove item if quantity is 0 or negative
                session.delete(cart_item)
                session.flush()
                CartService._invalidate_cart_cache(user.buyer_account.id)
                return None

            # Update quantity
            cart_item.quantity = quantity
            session.flush()

            # Update cache
            cart = session.query(Cart).get(cart_item.cart_id)
            CartService._cache_cart(cart)

            return cart_item

    @staticmethod
    def remove_from_cart(user_id: str, item_id: int) -> bool:
        """Remove item from cart"""
        with session_scope() as session:
            # Validate user
            user = session.query(User).get(user_id)
            if not user or not user.is_buyer:
                raise ForbiddenError("Only buyers can remove cart items")

            # Get cart item
            cart_item = (
                session.query(CartItem)
                .join(Cart)
                .filter(CartItem.id == item_id, Cart.buyer_id == user.buyer_account.id)
                .first()
            )

            if not cart_item:
                raise NotFoundError("Cart item not found")

            # Remove item
            session.delete(cart_item)
            session.flush()

            # Update cache
            CartService._invalidate_cart_cache(user.buyer_account.id)

            return True

    @staticmethod
    def clear_cart(user_id: str) -> bool:
        """Clear all items from cart"""
        with session_scope() as session:
            # Validate user
            user = session.query(User).get(user_id)
            if not user or not user.is_buyer:
                raise ForbiddenError("Only buyers can clear cart")

            # Get cart
            cart = session.query(Cart).filter_by(buyer_id=user.buyer_account.id).first()

            if not cart:
                return True  # No cart to clear

            # Clear cart items
            session.query(CartItem).filter_by(cart_id=cart.id).delete()
            session.flush()

            # Clear cache
            CartService._invalidate_cart_cache(user.buyer_account.id)

            return True

    @staticmethod
    def get_cart(user_id: str) -> Optional[Cart]:
        """Get user's cart with items"""
        # Try cache first
        cache_key = CartService.CART_CACHE_KEY.format(buyer_id=user_id)
        cached_cart = redis_client.get(cache_key)
        if cached_cart:
            return cached_cart

        with session_scope() as session:
            # Validate user
            user = session.query(User).get(user_id)
            if not user or not user.is_buyer:
                return None

            # Get cart with items
            cart = (
                session.query(Cart)
                .filter_by(buyer_id=user.buyer_account.id)
                .filter(Cart.expires_at > datetime.utcnow())
                .options(
                    joinedload("items").joinedload("product"),
                    joinedload("items").joinedload("variant"),
                )
                .first()
            )

            if cart:
                # Cache cart
                CartService._cache_cart(cart)

            return cart

    @staticmethod
    def checkout_cart(user_id: str, checkout_data: Dict[str, Any]) -> Order:
        """Convert cart to order and process checkout"""
        with session_scope() as session:
            # Validate user
            user = session.query(User).get(user_id)
            if not user or not user.is_buyer:
                raise ForbiddenError("Only buyers can checkout")

            # Get cart
            cart = CartService.get_cart(user_id)
            if not cart or not cart.items:
                raise ValidationError("Cart is empty")

            # Validate cart items (check availability, prices, etc.)
            CartService._validate_cart_items(cart.items)

            # Create order
            order = Order()
            order.buyer_id = user.buyer_account.id
            order.status = OrderStatus.PENDING
            order.subtotal = cart.subtotal()
            order.shipping_address = checkout_data.get("shipping_address")
            order.billing_address = checkout_data.get("billing_address")
            order.customer_note = checkout_data.get("notes")
            session.add(order)
            session.flush()

            # Create order items from cart items
            for cart_item in cart.items:
                order_item = OrderItem()
                order_item.order_id = order.id
                order_item.product_id = cart_item.product_id
                order_item.variant_id = cart_item.variant_id
                order_item.quantity = cart_item.quantity
                order_item.price = cart_item.product_price
                order_item.seller_id = cart_item.product.seller_id
                session.add(order_item)

            # Clear cart
            CartService.clear_cart(user_id)

            # Notify seller about new order
            CartService._notify_seller_new_order(order)

            return order

    @staticmethod
    def apply_coupon(user_id: str, coupon_code: str) -> Dict[str, Any]:
        """Apply coupon code to cart"""
        with session_scope() as session:
            # Validate user
            user = session.query(User).get(user_id)
            if not user or not user.is_buyer:
                raise ForbiddenError("Only buyers can apply coupons")

            # Get cart
            cart = session.query(Cart).filter_by(buyer_id=user.buyer_account.id).first()

            if not cart:
                raise ValidationError("No active cart found")

            # TODO: Implement coupon validation logic
            # For now, just store the coupon code
            cart.coupon_code = coupon_code
            session.flush()

            # Update cache
            CartService._cache_cart(cart)

            return {
                "success": True,
                "message": "Coupon applied successfully",
                "discount": 0,  # TODO: Calculate actual discount
            }

    @staticmethod
    def get_cart_summary(user_id: str) -> Dict[str, Any]:
        """Get cart summary for display"""
        cart = CartService.get_cart(user_id)
        if not cart:
            return {"item_count": 0, "subtotal": 0, "total": 0, "discount": 0}

        return {
            "item_count": cart.total_items(),
            "subtotal": cart.subtotal(),
            "total": cart.subtotal(),  # TODO: Add tax, shipping, discount
            "discount": 0,  # TODO: Calculate discount
        }

    # Private helper methods
    @staticmethod
    def _cache_cart(cart: Cart):
        """Cache cart data in Redis"""
        if cart:
            cache_key = CartService.CART_CACHE_KEY.format(buyer_id=cart.buyer_id)
            redis_client.set(cache_key, cart, ex=CartService.CACHE_EXPIRY)

    @staticmethod
    def _invalidate_cart_cache(buyer_id: int):
        """Invalidate cart cache"""
        cache_key = CartService.CART_CACHE_KEY.format(buyer_id=buyer_id)
        redis_client.delete(cache_key)

    @staticmethod
    def _validate_cart_items(cart_items: List[CartItem]):
        """Validate cart items for checkout"""
        for item in cart_items:
            # Check if product is still available
            if item.product.status != ProductStatus.ACTIVE:
                raise ValidationError(
                    f"Product {item.product.name} is no longer available"
                )

            # Check if price has changed significantly
            price_diff = (
                abs(item.product.price - item.product_price) / item.product_price
            )
            if price_diff > 0.1:  # 10% price change threshold
                raise ValidationError(f"Price for {item.product.name} has changed")

            # TODO: Check inventory availability
            # TODO: Check variant availability

    @staticmethod
    def _notify_seller_cart_addition(seller_id: int, product_id: str, quantity: int):
        """Notify seller when product is added to cart"""
        # TODO: Implement seller notification
        # This could be useful for inventory management

    @staticmethod
    def _notify_seller_new_order(order: Order):
        """Notify seller about new order"""
        # TODO: Implement seller notification
        # This should trigger email/SMS notifications
