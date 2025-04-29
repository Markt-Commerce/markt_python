from flask_smorest import Blueprint, abort
from flask.views import MethodView
from flask_login import login_user, logout_user, login_required, current_user
from sqlalchemy import and_

from .schemas import (
    BuyerSchema,
    SellerSchema,
    UserSchema,
    BuyerRegisterSchema,
    SellerRegisterSchema,
    CreateBuyerResponseSchema,
    CreateSellerResponseSchema,
    UserLoginSchema,
    UserLoginResponseSchema,
)
from .models import User, Buyer, Seller, UserAddress

"""from .utils import ImageSaver
from .models.imagename_store_model import ImageNameStore
import tempfile"""

auth_blp = Blueprint(
    "auth",
    __name__,
    description="Endpoint for all API calls related to user authentication",
    url_prefix="/auth",
)


@auth_blp.route("/register/buyer")
class BuyerRegister(MethodView):
    @auth_blp.arguments(BuyerRegisterSchema)
    @auth_blp.response(201, CreateBuyerResponseSchema)
    def post(self, buyer_data):
        existing_user = User.query.filter(
            and_(
                User.email == buyer_data["email"],
                User.is_buyer.is_(True),
            )
        ).first()

        if existing_user:
            abort(409, message="A buyer account with that email already exists.")

        existing_username = User.query.filter_by(
            username=buyer_data["username"]
        ).first()
        if existing_username:
            abort(409, message="A user with that username already exists.")

        new_user = User(
            email=buyer_data["email"],
            username=buyer_data["username"],
            phone_number=buyer_data["phone_number"],
            is_buyer=True,
        )
        new_user.save_to_db()

        new_buyer = Buyer(
            user_id=new_user.id,
            password=buyer_data["password"],
            buyername=buyer_data["buyername"],
            profile_picture=buyer_data.get(
                "profile_picture", "defaultThumbnailImageUrl"
            ),
            shipping_address=buyer_data.get("shipping_address"),
        )
        new_buyer.set_password(buyer_data["password"])
        new_buyer.save_to_db()

        if "address" in buyer_data:
            address_data = buyer_data["address"]
            user_address = UserAddress(
                user_id=new_user.id,
                longtitude=address_data.get("longtitude"),
                latitude=address_data.get("latitude"),
                house_number=address_data.get("house_number"),
                street=address_data.get("street"),
                city=address_data.get("city"),
                state=address_data.get("state"),
                postal_code=address_data.get("postal_code"),
            )
            user_address.save_to_db()

        # Log in the user and store current role in session
        login_user(new_user)
        new_user.current_role = "buyer"  # Set role in session

        user_data = {
            "id": new_user.id,
            "username": new_user.username,
            "email": new_user.email,
            "phone_number": new_user.phone_number,
            "profile_picture": new_user.profile_picture,
        }

        buyer_data = {
            "id": new_buyer.id,
            "buyername": new_buyer.buyername,
            "shipping_address": new_buyer.shipping_address,
            "user_status": new_buyer.user_status,
        }

        response = {"user": user_data, "buyer": buyer_data}

        # Return the response using the schema
        return CreateBuyerResponseSchema().dump(response), 201


@auth_blp.route("/register/seller")
class SellerRegister(MethodView):
    @auth_blp.arguments(SellerRegisterSchema)
    @auth_blp.response(201, CreateSellerResponseSchema)
    def post(self, seller_data):
        existing_user = User.query.filter(
            and_(User.email == seller_data["email"], User.is_seller.is_(True))
        ).first()

        if existing_user:
            abort(409, message="A seller account with that email already exists.")

        existing_username = User.query.filter_by(
            username=seller_data["username"]
        ).first()
        if existing_username:
            abort(409, message="A user with that username already exists.")

        new_user = User(
            email=seller_data["email"],
            username=seller_data["username"],
            phone_number=seller_data["phone_number"],
            is_seller=True,
        )
        new_user.save_to_db()

        new_seller = Seller(
            user_id=new_user.id,
            password=seller_data["password"],
            profile_picture=seller_data.get(
                "profile_picture", "defaultThumbnailImageUrl"
            ),
            shop_name=seller_data["shop_name"],
            description=seller_data["description"],
            directions=seller_data["directions"],
            category=seller_data["category"],
        )
        new_seller.set_password(seller_data["password"])
        new_seller.save_to_db()

        if "address" in seller_data:
            address_data = seller_data["address"]
            user_address = UserAddress(
                user_id=new_user.id,
                longtitude=address_data.get("longitude"),
                latitude=address_data.get("latitude"),
                house_number=address_data.get("house_number"),
                street=address_data.get("street"),
                city=address_data.get("city"),
                state=address_data.get("state"),
                postal_code=address_data.get("postal_code"),
            )
            user_address.save_to_db()

        # Log in the user and store current role in session
        login_user(new_user)
        new_user.current_role = "seller"  # Set role in session

        user_data = {
            "id": new_user.id,
            "username": new_user.username,
            "email": new_user.email,
            "phone_number": new_user.phone_number,
            "profile_picture": new_user.profile_picture,
        }

        seller_data = {
            "shop_name": new_seller.shop_name,
            "description": new_seller.description,
            "directions": new_seller.directions,
            "category": new_seller.category,
            "total_rating": new_seller.total_rating,
            "total_raters": new_seller.total_raters,
            "user_status": new_seller.user_status,
        }

        response = {"user": user_data, "seller": seller_data}

        # Return the response using the schema
        return CreateSellerResponseSchema().dump(response), 201


@auth_blp.route("/create-buyer")
class CreateBuyer(MethodView):
    @login_required
    @auth_blp.arguments(BuyerSchema)
    @auth_blp.response(201, CreateBuyerResponseSchema)
    def post(self, user_data):
        user = current_user
        if user.is_buyer:
            abort(409, message="User already has a buyer account.")

        user.is_buyer = True
        user.current_role = "buyer"
        user.save_to_db()

        new_buyer = Buyer(
            user_id=user.id,
            username=user_data["username"],
            password=user_data["password"],
            profile_picture=user_data.get(
                "profile_picture", "defaultThumbnailImageUrl"
            ),
            shipping_address=user_data.get("shipping_address"),
        )
        new_buyer.set_password(user_data["password"])
        new_buyer.save_to_db()

        user.current_role = "buyer"

        response = {
            "user": {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "current_role": user.current_role,
            },
            "buyer": {
                "id": new_buyer.id,
                "buyername": new_buyer.buyername,
                "shipping_address": new_buyer.shipping_address,
            },
        }

        return response, 201


@auth_blp.route("/create-seller")
class CreateSeller(MethodView):
    @login_required
    @auth_blp.arguments(SellerSchema)
    @auth_blp.response(201, CreateSellerResponseSchema)
    def post(self, user_data):
        user = current_user
        if user.is_seller:
            abort(409, message="User already has a seller account")

        user.is_seller = True
        user.current_role = "seller"
        user.save_to_db()

        new_seller = Seller(
            user_id=user.id,
            username=user_data["username"],
            password=user_data["password"],
            profile_picture=user_data.get(
                "profile_picture", "defaultThumbnailImageUrl"
            ),
            shop_name=user_data["shop_name"],
            description=user_data["description"],
            directions=user_data["directions"],
            category=user_data["category"],
        )
        new_seller.set_password(user_data["password"])
        new_seller.save_to_db()

        user.current_role = "seller"

        response = {
            "user": {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "current_role": user.current_role,
            },
            "seller": {
                "shop_name": new_seller.shop_name,
                "description": new_seller.description,
                "directions": new_seller.directions,
                "category": new_seller.category,
                "user_status": new_seller.user_status,
            },
        }

        return response, 201


@auth_blp.route("/switch-role")
class SwitchRole(MethodView):
    @login_required
    @auth_blp.response(200, description="User switched successfully.")
    def post(self):
        user = current_user

        if user.is_buyer or user.is_seller:
            if user.is_buyer and user.is_seller:
                # Switch the role and store it in Flask-Login session
                user.current_role = (
                    "seller" if user.current_role == "buyer" else "buyer"
                )
                return {
                    "message": "User switched successfully.",
                    "role": user.current_role,
                }, 200
            else:
                abort(
                    400,
                    message="User must have both buyer and seller accounts to switch roles.",
                )
        else:
            abort(
                400, message="User must have at least one account type to switch roles."
            )


@auth_blp.route("/login")
class UserLogin(MethodView):
    @auth_blp.arguments(UserLoginSchema)
    @auth_blp.response(200, UserLoginResponseSchema)
    def post(self, user_data):
        email = user_data["email"]
        password = user_data["password"]
        account_type = user_data["account_type"]

        user = User.query.filter_by(email=email).first()

        if user and account_type == "buyer" and user.is_buyer:
            buyer_account = Buyer.query.filter_by(user_id=user.id).first()
            if buyer_account and buyer_account.check_password(password):
                login_user(user)
                user.current_role = "buyer"
                return {"message": "Login successful", "current_role": "buyer"}, 200

        elif user and account_type == "seller" and user.is_seller:
            seller_account = Seller.query.filter_by(user_id=user.id).first()
            if seller_account and seller_account.check_password(password):
                login_user(user)
                user.current_role = "seller"
                return {"message": "Login successful", "current_role": "seller"}, 200

        abort(401, message="Invalid credentials.")


@auth_blp.route("/logout")
class UserLogout(MethodView):
    @login_required  # Protect this route
    @auth_blp.response(200, description="Logged out successfully")
    def post(self):
        logout_user()
        return {"message": "Logged out successful"}, 200


@auth_blp.route("/existinguser/<user_name>")
class UserNameCheck(MethodView):
    @auth_blp.response(200, description="Username checked successfully")
    def get(self, user_name):
        user = User.query.filter_by(username=user_name).first()
        if not user:
            return {"message": "not found"}, 404
        else:
            return {"message": "User With this username exists"}, 200
