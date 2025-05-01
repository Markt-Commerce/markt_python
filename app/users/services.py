# python imports
import random

# package imports
from sqlalchemy.orm import joinedload

# projects imports
from external.redis import redis_client
from app.libs.session import session_scope
from app.libs.errors import AuthError

# app imports
from .models import User, Buyer, Seller, UserAddress


class AuthService:
    @staticmethod
    def register_user(data):
        with session_scope() as session:
            # Check existing user
            if session.query(User).filter(User.email == data["email"]).first():
                raise AuthError("Email already registered")

            if session.query(User).filter(User.username == data["username"]).first():
                raise AuthError("Username already taken")

            # Create user
            user = User(
                email=data["email"],
                username=data["username"],
                phone_number=data.get("phone_number"),
                is_buyer=(data["account_type"] == "buyer"),
                is_seller=(data["account_type"] == "seller"),
            )
            session.add(user)
            session.flush()  # Get user ID

            # Create address
            if data.get("address"):
                address = UserAddress(user_id=user.id, **data["address"])
                session.add(address)

            # Create buyer/seller profile
            if data["account_type"] == "buyer":
                buyer = Buyer(
                    user_id=user.id,
                    buyername=data["buyer_data"]["buyername"],
                    shipping_address=data["buyer_data"].get("shipping_address"),
                )
                buyer.set_password(data["password"])
                session.add(buyer)
            else:
                seller = Seller(
                    user_id=user.id,
                    shop_name=data["seller_data"]["shop_name"],
                    description=data["seller_data"]["description"],
                    category=data["seller_data"]["category"],
                )
                seller.set_password(data["password"])
                session.add(seller)

            return user

    @staticmethod
    def login_user(email, password, account_type):
        with session_scope() as session:
            user = session.query(User).filter(User.email == email).first()
            if not user:
                raise AuthError("Invalid credentials")

            if account_type == "buyer" and user.buyer_account:
                if not user.buyer_account.check_password(password):
                    raise AuthError("Invalid credentials")
                user.current_role = "buyer"
            elif account_type == "seller" and user.seller_account:
                if not user.seller_account.check_password(password):
                    raise AuthError("Invalid credentials")
                user.current_role = "seller"
            else:
                raise AuthError("Invalid account type")

            return user

    @staticmethod
    def initiate_password_reset(email):
        code = str(random.randint(100000, 999999))
        redis_client.store_recovery_code(email, code)
        # In production: Send email with code
        return code  # For testing only

    @staticmethod
    def confirm_password_reset(email, code, new_password):
        if not redis_client.verify_recovery_code(email, code):
            raise AuthError("Invalid or expired code")

        with session_scope() as session:
            user = session.query(User).filter(User.email == email).first()
            if not user:
                raise AuthError("User not found")

            if user.buyer_account:
                user.buyer_account.set_password(new_password)
            elif user.seller_account:
                user.seller_account.set_password(new_password)
            else:
                raise AuthError("No valid account type")

            redis_client.delete_recovery_code(email)
            return True


class UserService:
    @staticmethod
    def get_user_profile(user_id):
        with session_scope() as session:
            user = (
                session.query(User)
                .options(
                    joinedload(User.address),
                    joinedload(User.buyer_account),
                    joinedload(User.seller_account),
                )
                .get(user_id)
            )

            if not user:
                raise AuthError("User not found")

            return user

    @staticmethod
    def switch_role(user_id):
        with session_scope() as session:
            user = session.query(User).get(user_id)
            if not user:
                raise AuthError("User not found")

            if not (user.is_buyer and user.is_seller):
                raise AuthError("User doesn't have both account types")

            user.current_role = "seller" if user.current_role == "buyer" else "buyer"
            session.commit()
            return user
