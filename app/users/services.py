# python imports
import random

# package imports
from sqlalchemy.orm import joinedload
from sqlalchemy import func

# projects imports
from external.redis import redis_client
from app.libs.session import session_scope
from app.libs.errors import AuthError
from app.libs.pagination import Paginator

# app imports
from .models import User, Buyer, Seller, UserAddress
from .constants import RESERVED_USERNAMES


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
            user.set_password(data["password"])  # Set password at user level
            session.add(user)
            session.flush()

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
                session.add(buyer)
            else:
                seller = Seller(
                    user_id=user.id,
                    shop_name=data["seller_data"]["shop_name"],
                    description=data["seller_data"]["description"],
                    category=data["seller_data"]["category"],
                )
                session.add(seller)

            return user

    @staticmethod
    def login_user(email, password, account_type):
        with session_scope() as session:
            user = session.query(User).filter(User.email == email).first()
            if not user or not user.check_password(password):
                raise AuthError("Invalid credentials")

            if account_type == "buyer" and not user.is_buyer:
                raise AuthError("Buyer account not found")
            if account_type == "seller" and not user.is_seller:
                raise AuthError("Seller account not found")

            user.current_role = account_type
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

            user.set_password(new_password)

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
    def list_users(args):
        """Get paginated list of users with filters"""
        from sqlalchemy import or_

        query = User.query
        paginator = Paginator(
            query, page=args.get("page", 1), per_page=args.get("per_page", 20)
        )

        if "search" in args:
            search = f"%{args['search']}%"
            paginator.query = paginator.query.filter(
                or_(User.username.ilike(search), User.email.ilike(search))
            )

        result = paginator.paginate(args)
        return {
            "items": result["items"],
            "pagination": {
                "page": result["page"],
                "per_page": result["per_page"],
                "total_items": result["total_items"],
                "total_pages": result["total_pages"],
            },
        }

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

    @staticmethod
    def check_username_availability(username):
        with session_scope() as session:
            exists = session.query(
                session.query(User)
                .filter(func.lower(User.username) == func.lower(username))
                .exists()
            ).scalar()

            return {
                "available": not exists,
                "message": "Username is already taken"
                if exists
                else "Username available",
            }
