from flask_smorest import Blueprint, abort
from flask.views import MethodView
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from ..schemas import (
    BuyerSchema,
    BuyerUpdateSchema,
    SellerSchema,
    SellerUpdateSchema,
    UserSchema,
    UserProfileSchema,
    RoleArgSchema,
    UserProfileUpdateSchema,
    UpdateProfilePictureSchema,
)
from ..models import User, Buyer, Seller

user_blp = Blueprint(
    "users",
    __name__,
    description="Endpoint for all API calls related to users",
    url_prefix="/user",
)


@user_blp.route("/<int:user_id>")
class UserResource(MethodView):
    # functions here are used for testing
    @login_required  # Protect this route
    @user_blp.response(200, UserSchema)
    def get(self, user_id):
        user = User.query.get_or_404(user_id)
        return user

    def post(self, user_id):
        pass

    def put(self, user_id):
        pass


@user_blp.route("/buyer")
class BuyerResource(MethodView):
    @login_required
    @user_blp.response(200, BuyerSchema)
    def get(self):
        buyer_info = Buyer.query.filter_by(user_id=current_user.id).first()
        if buyer_info:
            return {
                "buyername": buyer_info.buyername,
                "email": current_user.email,
                "phone_number": current_user.phone_number or None,
                "profile_picture": buyer_info.profile_picture,
                "shipping_address": buyer_info.shipping_address,
                "user_status": buyer_info.user_status,
            }, 200
        abort(404, message="Buyer not found")

    @login_required
    @user_blp.arguments(BuyerUpdateSchema)
    @user_blp.response(200, description="Buyer profile updated successfully.")
    def put(self, user_data):
        buyer_info = Buyer.query.filter_by(user_id=current_user.id).first()
        if buyer_info:
            # Update buyer information based on the data received
            buyer_info.buyername = user_data.get("buyername", buyer_info.buyername)
            buyer_info.shipping_address = user_data.get(
                "shipping_address", buyer_info.shipping_address
            )
            buyer_info.save_to_db()
            return {"message": "Buyer profile updated successfully."}, 200

        abort(404, message="Buyer not found")

    def delete(self):
        #  Deletion considerations TBD
        pass


@user_blp.route("/seller")
class SellerResource(MethodView):
    @login_required
    @user_blp.response(200, SellerSchema)
    def get(self):
        seller_info = Seller.query.filter_by(user_id=current_user.id).first()
        if seller_info:
            return {
                "email": current_user.email,
                "profile_picture": seller_info.profile_picture,
                "shop_name": seller_info.shop_name,
                "description": seller_info.description,
                "directions": seller_info.directions,
                "category": seller_info.category,
                "total_rating": seller_info.total_rating,
                "total_raters": seller_info.total_raters,
                "user_status": seller_info.user_status,
            }, 200

        abort(404, message="Seller not found")

    @login_required
    @user_blp.arguments(SellerUpdateSchema)
    @user_blp.response(200, description="Seller profile updated successfully.")
    def put(self, user_data):
        seller_info = Seller.query.filter_by(user_id=current_user.id).first()
        if seller_info:
            # Update seller information based on the data received
            # seller_info.username = user_data.get("username", seller_info.username)
            seller_info.shop_name = user_data.get("shop_name", seller_info.shop_name)
            seller_info.save_to_db()
            return {"message": "Seller profile updated successfully."}, 200

        abort(404, message="Seller not found")

    def delete(self):
        #  Deletion considerations TBD
        pass


@user_blp.route("/profile")
class UserProfile(MethodView):
    @login_required
    @user_blp.arguments(RoleArgSchema, required=False)
    @user_blp.response(200, UserProfileSchema)
    def get(self, user_data):
        role = user_data.get(
            "role", None
        )  # 'buyer', 'seller', or None for current role

        if role and current_user.current_role != role:
            abort(400, message=f"User does not have a {role} account.")

        if role:
            # Return user information based on the requested role
            if role == "buyer":
                buyer_info = Buyer.query.filter_by(user_id=current_user.id).first()
                if buyer_info:
                    return UserProfileSchema.dump_buyer_info(buyer_info), 200
            elif role == "seller":
                seller_info = Seller.query.filter_by(user_id=current_user.id).first()
                if seller_info:
                    return UserProfileSchema.dump_seller_info(seller_info), 200
            else:
                abort(400, message=f"Invalid role: {role}")
        else:
            # Return user information based on the current role
            if current_user.is_buyer:
                buyer = Buyer.query.filter_by(user_id=current_user.id).first()
                if buyer:
                    buyer_info = {
                        "username": buyer.username,
                        "email": current_user.email,
                        "phone_number": current_user.phone_number or None,
                        "profile_picture": buyer.profile_picture,
                        "shipping_address": buyer.shipping_address,
                    }
                    return UserProfileSchema.dump_buyer_info(buyer_info), 200
            elif current_user.is_seller:
                seller = Seller.query.filter_by(user_id=current_user.id).first()
                if seller:
                    seller_info = {
                        # "username": seller.username,
                        "email": current_user.email,
                        "profile_picture": seller.profile_picture,
                        "shop_name": seller.shop_name,
                        "description": seller.description,
                        "directions": seller.directions,
                        "category": seller.category,
                        "total_rating": seller.total_rating,
                        "total_raters": seller.total_raters,
                    }
                    return UserProfileSchema.dump_seller_info(seller_info), 200

        abort(404, message="User profile not found")

    @login_required
    @user_blp.arguments(UserProfileUpdateSchema)
    @user_blp.response(200, description="Profile updated successfully")
    def put(self, user_data):
        # Validate user_data based on user's role, and update the profile accordingly

        if current_user.current_role == "buyer":
            # Update buyer-related info
            buyer = Buyer.query.filter_by(user_id=current_user.id).first()
            buyer_info = user_data.get("buyer_info", {})

            if buyer_info:
                # Update buyer information based on the data received
                buyer.buyername = buyer_info.get("buyername", buyer.buyername)
                buyer.shipping_address = buyer_info.get(
                    "shipping_address", buyer.shipping_address
                )
                buyer.save_to_db()

        elif current_user.current_role == "seller":
            # Update seller-related info
            seller = Seller.query.filter_by(user_id=current_user.id).first()
            seller_info = user_data.get("seller_info", {})

            if seller_info:
                # Update seller information based on the data received
                seller.username = seller_info.get("username", seller.username)
                seller.shop_name = seller_info.get("shop_name", seller.shop_name)
                seller.save_to_db()

        else:
            # Update common user info
            # For example, updating email or phone_number
            current_user.email = user_data.get("email", current_user.email)
            current_user.phone_number = user_data.get(
                "phone_number", current_user.phone_number
            )
            current_user.save_to_db()

        # Return a response as needed
        return {"message": "Profile updated successfully"}, 200


# TODO: Add configuration for file storage (e.g., AWS S3, local file system)
# TODO: Implement image compression and thumbnail generation


@user_blp.route("/update-profile-picture")
class ProfilePictureResource(MethodView):
    @login_required
    @user_blp.arguments(UpdateProfilePictureSchema)
    @user_blp.response(200, description="Profile picture updated successfully")
    def patch(self, user_data):
        # TODO: Handle file upload and storage
        uploaded_file = user_data.get("profile_picture")

        if not uploaded_file:
            abort(400, message="No file provided")

        # TODO: Validate file type and size
        allowed_extensions = {"png", "jpg", "jpeg", "gif"}
        if (
            "." not in uploaded_file.filename
            or uploaded_file.filename.split(".")[-1].lower() not in allowed_extensions
        ):
            abort(400, message="Invalid file type")

        # TODO: Securely generate file name and save to storage
        filename = secure_filename(uploaded_file.filename)
        # storage_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        # uploaded_file.save(storage_path)

        # TODO: Update user's profile picture URL in the database
        current_user.profile_picture = f"/uploads/{filename}"
        current_user.save_to_db()

        # TODO: Return profile picture URL or thumbnail URL in the response
        return {"message": "Profile picture updated successfully"}, 200
