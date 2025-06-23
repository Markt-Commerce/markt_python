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
    def update_user_profile(user_id, data):
        with session_scope() as session:
            user = session.query(User).get(user_id)
            if not user:
                raise AuthError("User not found")

            if "phone_number" in data:
                user.phone_number = data["phone_number"]
            if "profile_picture" in data:
                user.profile_picture = data["profile_picture"]
            if "university" in data:
                # Handle university info update
                pass

            session.commit()
            return user

    @staticmethod
    def update_buyer_profile(user_id, data):
        with session_scope() as session:
            buyer = session.query(Buyer).filter_by(user_id=user_id).first()
            if not buyer:
                raise AuthError("Buyer account not found")

            if "buyername" in data:
                buyer.buyername = data["buyername"]
            if "shipping_address" in data:
                buyer.shipping_address = data["shipping_address"]

            session.commit()
            return buyer

    @staticmethod
    def update_seller_profile(user_id, data):
        with session_scope() as session:
            seller = session.query(Seller).filter_by(user_id=user_id).first()
            if not seller:
                raise AuthError("Seller account not found")

            if "shop_name" in data:
                seller.shop_name = data["shop_name"]
            if "description" in data:
                seller.description = data["description"]
            if "category" in data:
                seller.category = data["category"]
            if "policies" in data:
                seller.policies = data["policies"]

            session.commit()
            return seller

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
        username_lower = username.lower()

        with session_scope() as session:
            # Check reserved names
            if username_lower in [name.lower() for name in RESERVED_USERNAMES]:
                return {"available": False, "message": "This username is reserved"}
            exists = session.query(
                session.query(User)
                .filter(func.lower(User.username) == username_lower)
                .exists()
            ).scalar()

            return {
                "available": not exists,
                "message": "Username is already taken"
                if exists
                else "Username available",
            }


class AccountService:
    @staticmethod
    def create_buyer_account(user_id, data):
        with session_scope() as session:
            user = session.query(User).get(user_id)
            if not user:
                raise AuthError("User not found")
            if user.is_buyer:
                raise AuthError("Buyer account already exists")

            buyer = Buyer(
                user_id=user.id,
                buyername=data["buyername"],
                shipping_address=data.get("shipping_address"),
            )

            if data.get("university"):
                # Handle university verification logic
                pass

            session.add(buyer)
            user.is_buyer = True
            return buyer

    @staticmethod
    def create_seller_account(user_id, data):
        with session_scope() as session:
            user = session.query(User).get(user_id)
            if not user:
                raise AuthError("User not found")
            if user.is_seller:
                raise AuthError("Seller account already exists")

            seller = Seller(
                user_id=user.id,
                shop_name=data["shop_name"],
                description=data["description"],
                category=data["category"],
                policies=data.get("policies", {}),
            )

            if data.get("university"):
                # Handle university verification logic
                pass

            session.add(seller)
            user.is_seller = True
            return seller
