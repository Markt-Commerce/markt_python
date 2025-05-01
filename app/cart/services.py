from libs.session import session_scope
from external.redis import redis_client
from .models import Cart


class CartService:
    @staticmethod
    def get_cart(user_id):
        # Try Redis first
        cart = redis_client.get(f"cart:{user_id}")
        if cart:
            return cart

        # Fallback to DB
        with session_scope() as session:
            return session.query(Cart).filter_by(user_id=user_id).first()

    @staticmethod
    def update_cart(user_id, items):
        # Update both Redis and DB
        redis_client.setex(f"cart:{user_id}", 3600, items)

        with session_scope() as session:
            cart = session.query(Cart).filter_by(user_id=user_id).first()
            if cart:
                cart.items = items
            else:
                cart = Cart(user_id=user_id, items=items)
                session.add(cart)
            return cart

    # TODO: Add cart merging (guest -> user)
    # TODO: Add promotional calculations
