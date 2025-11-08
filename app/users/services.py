# python imports
import random
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List

# package imports
from sqlalchemy.orm import joinedload
from sqlalchemy import func, and_, or_

# projects imports
from external.redis import redis_client
from external.database import db
from app.libs.session import session_scope
from app.libs.errors import AuthError, NotFoundError, APIError, UnverifiedEmailError
from app.libs.pagination import Paginator
from app.libs.email_service import email_service

from app.products.models import Product
from app.socials.models import Post, PostStatus, Follow, ProductView
from app.media.services import media_service
from app.media.models import Media, MediaVariantType, MediaVariant
from app.categories.models import Category, SellerCategory
from app.libs.errors import ValidationError
from app.orders.models import OrderItem

# app imports
from .models import User, Buyer, Seller, UserAddress, SellerVerificationStatus
from .constants import (
    RESERVED_USERNAMES,
    PROFILE_SETUP_HREF,
    ADD_FIRST_PRODUCT_HREF,
    VERIFY_EMAIL_HREF,
    VIEW_ORDERS_HREF,
    CREATE_POST_HREF,
)

logger = logging.getLogger(__name__)


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
                    policies=data["seller_data"].get("policies", {}),
                )
                session.add(seller)
                session.flush()  # Get the seller ID

                # Handle category relationships
                if "category_ids" in data["seller_data"]:
                    for idx, category_id in enumerate(
                        data["seller_data"]["category_ids"]
                    ):
                        # Verify category exists
                        category = session.query(Category).get(category_id)
                        if not category:
                            raise ValidationError(f"Category {category_id} not found")

                        # Create seller category relationship
                        seller_category = SellerCategory(
                            seller_id=seller.id,
                            category_id=category_id,
                            is_primary=(idx == 0),  # First category is primary
                        )
                        session.add(seller_category)

            # Explicitly set current_role during registration
            user.current_role = data["account_type"]

            session.commit()
            return user

    @staticmethod
    def login_user(email, password, account_type=None):
        with session_scope() as session:
            user = session.query(User).filter(User.email == email).first()
            if not user or not user.check_password(password):
                raise AuthError("Invalid credentials")

            # Check if user is active
            if not user.is_active:
                raise AuthError("Account is deactivated")

            # Intelligent login: if account_type not provided, use current_role or default
            if account_type is None:
                # Use current_role if set, otherwise determine based on available accounts
                if hasattr(user, "_current_role") and user._current_role:
                    account_type = user._current_role
                elif user.is_buyer and user.is_seller:
                    # If user has both accounts, default to buyer
                    account_type = "buyer"
                elif user.is_buyer:
                    account_type = "buyer"
                elif user.is_seller:
                    account_type = "seller"
                else:
                    raise AuthError("No valid account type found")

            # Validate the account type
            if account_type == "buyer":
                if not user.is_buyer:
                    raise AuthError("Buyer account not found")

                # Check if buyer account is active
                buyer = session.query(Buyer).filter_by(user_id=user.id).first()
                if not buyer:
                    raise AuthError("Buyer account not found")
                if not buyer.is_active:
                    raise AuthError("Buyer account is deactivated")

            elif account_type == "seller":
                if not user.is_seller:
                    raise AuthError("Seller account not found")

                # Check if seller account is active
                seller = session.query(Seller).filter_by(user_id=user.id).first()
                if not seller:
                    raise AuthError("Seller account not found")
                if not seller.is_active:
                    raise AuthError("Seller account is deactivated")
            else:
                raise AuthError("Invalid account type")

            # Check email verification for new accounts
            if not user.email_verified:
                raise UnverifiedEmailError(
                    "Please verify your email address before logging in. Use the email verification endpoint to send a verification code.",
                    payload={"email": user.email},
                )

            # Update current_role and last login timestamp
            user.current_role = account_type
            try:
                # Update last login time for session management on frontend
                from datetime import datetime

                user.last_login_at = datetime.utcnow()
                session.commit()
            except Exception as e:
                logger.warning(f"Failed to update last_login_at for {user.id}: {e}")
            return user

    @staticmethod
    def initiate_password_reset(email):
        """Initiate password reset process by sending reset code via email"""
        with session_scope() as session:
            user = session.query(User).filter(User.email == email).first()
            if not user:
                # Don't reveal if email exists or not for security
                logger.info(f"Password reset requested for non-existent email: {email}")
                return True

            # Generate reset code
            reset_code = str(random.randint(100000, 999999))

            # Store reset code in Redis (10 minutes expiration)
            redis_client.store_recovery_code(email, reset_code, expires_in=600)

            # Send password reset email
            try:
                success = email_service.send_password_reset_email(
                    email=user.email,
                    reset_code=reset_code,
                    username=user.username,
                )

                if not success:
                    # Clean up Redis if email fails
                    redis_client.delete_recovery_code(user.email)
                    logger.error(f"Failed to send password reset email to {user.email}")
                    raise AuthError("Failed to send password reset email")

                logger.info(f"Password reset email sent successfully to {user.email}")
                return True

            except Exception as e:
                # Clean up Redis if email fails
                redis_client.delete_recovery_code(user.email)
                logger.error(
                    f"Error sending password reset email to {user.email}: {str(e)}"
                )
                raise AuthError("Failed to send password reset email")

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

    @staticmethod
    def generate_verification_code():
        """Generate a 6-digit verification code"""
        return str(random.randint(100000, 999999))

    @staticmethod
    def send_email_verification(email: str):
        """Send email verification code to user by email address"""
        with session_scope() as session:
            user = session.query(User).filter(User.email == email).first()
            if not user:
                raise AuthError("User not found")

            if user.email_verified:
                raise AuthError("Email already verified")

            # Generate verification code
            verification_code = AuthService.generate_verification_code()

            # Store verification code in Redis (10 minutes expiration)
            redis_client.store_verification_code(
                user.email, verification_code, expires_in=600
            )

            # Send verification email
            success = email_service.send_verification_email(
                email=user.email,
                verification_code=verification_code,
                username=user.username,
            )

            if not success:
                # Clean up Redis if email fails
                redis_client.delete_verification_code(user.email)
                raise AuthError("Failed to send verification email")

            return True

    @staticmethod
    def verify_email(email: str, verification_code: str):
        """Verify user email with code"""
        with session_scope() as session:
            user = session.query(User).filter(User.email == email).first()
            if not user:
                raise AuthError("User not found")

            if user.email_verified:
                raise AuthError("Email already verified")

            # Verify code from Redis
            if not redis_client.verify_verification_code(user.email, verification_code):
                raise AuthError("Invalid or expired verification code")

            # Mark email as verified
            user.email_verified = True

            # Clean up verification code from Redis
            redis_client.delete_verification_code(user.email)

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
                    joinedload(User.seller_account)
                    .joinedload(Seller.categories)
                    .joinedload(SellerCategory.category),
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
            if "policies" in data:
                seller.policies = data["policies"]

            # Handle category updates
            if "category_ids" in data:
                # Remove existing category relationships
                session.query(SellerCategory).filter_by(seller_id=seller.id).delete()

                # Add new category relationships
                for idx, category_id in enumerate(data["category_ids"]):
                    # Verify category exists
                    category = session.query(Category).get(category_id)
                    if not category:
                        raise ValidationError(f"Category {category_id} not found")

                    # Create seller category relationship
                    seller_category = SellerCategory(
                        seller_id=seller.id,
                        category_id=category_id,
                        is_primary=(idx == 0),  # First category is primary
                    )
                    session.add(seller_category)

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

            # Verify user has both account types
            if not (user.is_buyer and user.is_seller):
                raise AuthError("User doesn't have both account types")

            # Ensure _current_role is explicitly set to avoid default property logic
            if not hasattr(user, "_current_role") or not user._current_role:
                # If not set, determine from is_buyer/is_seller flags
                # Default to buyer if both exist
                user._current_role = "buyer" if user.is_buyer else "seller"

            # Get previous role before switching
            previous_role = user._current_role

            # Switch to the opposite role
            new_role = "seller" if previous_role == "buyer" else "buyer"
            user.current_role = new_role

            session.commit()

            return {
                "success": True,
                "previous_role": previous_role,
                "current_role": user.current_role,
                "message": f"Successfully switched from {previous_role} to {user.current_role}",
                "user": user,
            }

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

    @staticmethod
    def user_exists(user_id: str) -> bool:
        """Check if a user exists"""
        try:
            with session_scope() as session:
                user = session.query(User).filter(User.id == user_id).first()
                return user is not None
        except Exception as e:
            logger.error(f"Error checking if user exists: {e}")
            return False

    @staticmethod
    def upload_profile_picture(user_id: str, file_stream, filename: str):
        """Upload and set user profile picture (idempotent: deletes old one)"""
        try:
            from io import BytesIO
            from app.media.models import MediaVariantType, Media
            from app.media.services import media_service
            from urllib.parse import urlparse

            # Ensure file_stream is BytesIO
            if not isinstance(file_stream, BytesIO):
                file_stream = BytesIO(file_stream.read())

            # 1. Delete old profile picture if it exists
            with session_scope() as session:
                user = session.query(User).get(user_id)
                if not user:
                    raise AuthError("User not found")

                if user.profile_picture:
                    # Extract storage_key from the URL
                    old_url = user.profile_picture
                    parsed = urlparse(old_url)
                    storage_key = parsed.path.lstrip("/")
                    old_media = (
                        session.query(Media).filter_by(storage_key=storage_key).first()
                    )
                    if old_media:
                        # Delete from S3
                        media_service.delete_media(old_media)
                        # Delete variants from DB
                        session.query(MediaVariant).filter_by(
                            media_id=old_media.id
                        ).delete()
                        # Delete media from DB
                        session.delete(old_media)
                        session.commit()
                        user.profile_picture = None
                        session.commit()

            # 2. Upload media using updated media service (returns only media object)
            media = media_service.upload_image(
                file_stream=file_stream,
                filename=filename,
                user_id=user_id,
                alt_text=f"Profile picture for user {user_id}",
                caption="Profile picture",
                is_profile_picture=True,
            )

            # 3. Update user profile picture with original URL (thumbnail will be set async)
            with session_scope() as session:
                user = session.query(User).get(user_id)
                if not user:
                    raise AuthError("User not found")
                user.profile_picture = media.get_url()  # Original URL for now
                session.commit()

            return {
                "success": True,
                "media": media,
                "profile_picture_url": user.profile_picture,
            }

        except Exception as e:
            logger.error(f"Failed to upload profile picture: {e}")
            raise AuthError(f"Failed to upload profile picture: {str(e)}")


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

            # Ensure current_role is set if not already set
            if not hasattr(user, "_current_role") or not user._current_role:
                # If user already has seller account, keep seller role
                # Otherwise set to buyer
                user.current_role = "seller" if user.is_seller else "buyer"

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
                policies=data.get("policies", {}),
            )
            session.add(seller)
            session.flush()  # Get the seller ID

            # Handle category relationships
            if "category_ids" in data:
                for idx, category_id in enumerate(data["category_ids"]):
                    # Verify category exists
                    category = session.query(Category).get(category_id)
                    if not category:
                        raise ValidationError(f"Category {category_id} not found")

                    # Create seller category relationship
                    seller_category = SellerCategory(
                        seller_id=seller.id,
                        category_id=category_id,
                        is_primary=(idx == 0),  # First category is primary
                    )
                    session.add(seller_category)

            if data.get("university"):
                # Handle university verification logic
                pass

            session.add(seller)
            user.is_seller = True

            # Ensure current_role is set if not already set
            if not hasattr(user, "_current_role") or not user._current_role:
                # If user already has buyer account, keep buyer role
                # Otherwise set to seller
                user.current_role = "buyer" if user.is_buyer else "seller"

            return seller

    @staticmethod
    def deactivate_user(user_id: str) -> bool:
        """Deactivate a user account"""
        with session_scope() as session:
            user = session.query(User).get(user_id)
            if not user:
                raise NotFoundError("User not found")

            user.deactivate()
            session.commit()
            return True

    @staticmethod
    def activate_user(user_id: str) -> bool:
        """Activate a user account"""
        try:
            with session_scope() as session:
                user = session.query(User).filter(User.id == user_id).first()
                if not user:
                    raise NotFoundError("User not found")

                user.activate()
                session.commit()
                return True
        except Exception as e:
            logger.error(f"Failed to activate user: {str(e)}")
            return False

    @staticmethod
    def deactivate_buyer_account(user_id: str) -> bool:
        """Deactivate a buyer account"""
        try:
            with session_scope() as session:
                buyer = session.query(Buyer).filter_by(user_id=user_id).first()
                if not buyer:
                    raise NotFoundError("Buyer account not found")

                buyer.deactivate()
                session.commit()
                return True
        except Exception as e:
            logger.error(f"Failed to deactivate buyer account: {str(e)}")
            return False

    @staticmethod
    def activate_buyer_account(user_id: str) -> bool:
        """Activate a buyer account"""
        try:
            with session_scope() as session:
                buyer = session.query(Buyer).filter_by(user_id=user_id).first()
                if not buyer:
                    raise NotFoundError("Buyer account not found")

                buyer.activate()
                session.commit()
                return True
        except Exception as e:
            logger.error(f"Failed to activate buyer account: {str(e)}")
            return False

    @staticmethod
    def deactivate_seller_account(user_id: str) -> bool:
        """Deactivate a seller account"""
        try:
            with session_scope() as session:
                seller = session.query(Seller).filter_by(user_id=user_id).first()
                if not seller:
                    raise NotFoundError("Seller account not found")

                seller.deactivate()
                session.commit()
                return True
        except Exception as e:
            logger.error(f"Failed to deactivate seller account: {str(e)}")
            return False

    @staticmethod
    def activate_seller_account(user_id: str) -> bool:
        """Activate a seller account"""
        try:
            with session_scope() as session:
                seller = session.query(Seller).filter_by(user_id=user_id).first()
                if not seller:
                    raise NotFoundError("Seller account not found")

                seller.activate()
                session.commit()
                return True
        except Exception as e:
            logger.error(f"Failed to activate seller account: {str(e)}")
            return False


class ShopService:
    """Service for shop/seller discovery and search"""

    @staticmethod
    def search_shops(args, user_id=None):
        """Search for shops with filters and pagination"""
        try:
            with session_scope() as session:
                # Build base query
                query = session.query(Seller).join(User)

                # Apply filters
                if args.get("search"):
                    search_term = f"%{args['search']}%"
                    query = query.filter(
                        db.or_(
                            Seller.shop_name.ilike(search_term),
                            Seller.description.ilike(search_term),
                            User.username.ilike(search_term),
                        )
                    )

                if args.get("category"):
                    query = query.filter(Seller.category == args["category"])

                if args.get("verified_only"):
                    query = query.filter(
                        Seller.verification_status == SellerVerificationStatus.VERIFIED
                    )

                if args.get("active_only"):
                    query = query.filter(Seller.is_active == True)

                # Apply sorting
                sort_by = args.get("sort_by", "rating")
                if sort_by == "rating":
                    query = query.order_by(Seller.total_rating.desc())
                elif sort_by == "name":
                    query = query.order_by(Seller.shop_name.asc())
                elif sort_by == "recent":
                    query = query.order_by(Seller.created_at.desc())
                elif sort_by == "followers":
                    # This would need a join with follows table
                    query = query.order_by(Seller.created_at.desc())  # Fallback

                # Get total count
                total = query.count()

                # Apply pagination
                page = args.get("page", 1)
                per_page = min(args.get("per_page", 20), 100)
                offset = (page - 1) * per_page

                shops = query.offset(offset).limit(per_page).all()

                # Enhance with additional data
                enhanced_shops = []
                for shop in shops:
                    shop_data = {
                        "id": shop.id,
                        "shop_name": shop.shop_name,
                        "shop_slug": shop.shop_slug,
                        "description": shop.description,
                        "categories": [
                            {
                                "id": sc.category.id,
                                "name": sc.category.name,
                                "slug": sc.category.slug,
                            }
                            for sc in shop.categories
                        ],
                        "verification_status": shop.verification_status.value,
                        "is_active": shop.is_active,
                        "total_rating": shop.total_rating,
                        "total_raters": shop.total_raters,
                        "average_rating": shop.total_rating / shop.total_raters
                        if shop.total_raters > 0
                        else 0,
                        "user": {
                            "id": shop.user.id,
                            "username": shop.user.username,
                            "profile_picture": shop.user.profile_picture,
                        },
                        "stats": ShopService._get_shop_stats(shop.id),
                    }

                    # Add follow status if user is authenticated
                    if user_id:
                        shop_data["is_followed"] = ShopService._is_followed_by_user(
                            shop.user_id, user_id
                        )

                    enhanced_shops.append(shop_data)

                return {
                    "shops": enhanced_shops,
                    "pagination": {
                        "page": page,
                        "per_page": per_page,
                        "total": total,
                        "pages": (total + per_page - 1) // per_page,
                        "has_next": offset + per_page < total,
                        "has_prev": page > 1,
                    },
                }

        except Exception as e:
            logger.error(f"Shop search failed: {str(e)}")
            raise APIError("Failed to search shops")

    @staticmethod
    def get_shop_details(shop_id, user_id=None):
        """Get detailed shop information"""
        try:
            with session_scope() as session:
                shop = (
                    session.query(Seller)
                    .options(joinedload(Seller.user))
                    .filter(Seller.id == shop_id)
                    .first()
                )

                if not shop:
                    raise NotFoundError("Shop not found")

                # Get shop statistics
                stats = ShopService._get_shop_stats(shop_id)

                # Get recent products
                recent_products = (
                    session.query(Product)
                    .filter(
                        Product.seller_id == shop_id,
                        Product.status == Product.Status.ACTIVE,
                    )
                    .order_by(Product.created_at.desc())
                    .limit(6)
                    .all()
                )

                # Get recent posts
                # Post is now user-level; get posts from the shop owner's user account
                recent_posts = (
                    session.query(Post)
                    .filter(
                        Post.user_id == shop.user_id, Post.status == PostStatus.ACTIVE
                    )
                    .order_by(Post.created_at.desc())
                    .limit(6)
                    .all()
                )

                shop_data = {
                    "id": shop.id,
                    "shop_name": shop.shop_name,
                    "shop_slug": shop.shop_slug,
                    "description": shop.description,
                    "categories": [
                        {
                            "id": sc.category.id,
                            "name": sc.category.name,
                            "slug": sc.category.slug,
                        }
                        for sc in shop.categories
                    ],
                    "verification_status": shop.verification_status.value,
                    "is_active": shop.is_active,
                    "total_rating": shop.total_rating,
                    "total_raters": shop.total_raters,
                    "average_rating": shop.total_rating / shop.total_raters
                    if shop.total_raters > 0
                    else 0,
                    "policies": shop.policies,
                    "user": {
                        "id": shop.user.id,
                        "username": shop.user.username,
                        "profile_picture": shop.user.profile_picture,
                    },
                    "stats": stats,
                    "recent_products": [
                        {
                            "id": product.id,
                            "name": product.name,
                            "price": float(product.price),
                            "image": ShopService._get_primary_product_image(product),
                        }
                        for product in recent_products
                    ],
                    "recent_posts": [
                        {
                            "id": post.id,
                            "caption": post.caption,
                            "media": [
                                {"url": m.media_url, "type": m.media_type}
                                for m in post.social_media
                            ],
                            "likes_count": len(post.likes),
                            "comments_count": len(post.comments),
                            "created_at": post.created_at.isoformat(),
                        }
                        for post in recent_posts
                    ],
                }

                # Add follow status if user is authenticated
                if user_id:
                    shop_data["is_followed"] = ShopService._is_followed_by_user(
                        shop.user_id, user_id
                    )
                    shop_data["can_follow"] = shop.user_id != user_id

                return shop_data

        except NotFoundError:
            raise
        except Exception as e:
            logger.error(f"Failed to get shop details: {str(e)}")
            raise APIError("Failed to get shop details")

    @staticmethod
    def get_trending_shops(limit=10):
        """Get trending shops based on engagement"""
        try:
            with session_scope() as session:
                # Get shops with high engagement (followers, ratings, recent activity)
                trending_shops = (
                    session.query(Seller)
                    .join(User)
                    .filter(
                        Seller.is_active == True,
                        Seller.verification_status == SellerVerificationStatus.VERIFIED,
                    )
                    .order_by(Seller.total_rating.desc(), Seller.created_at.desc())
                    .limit(limit)
                    .all()
                )

                return [
                    {
                        "id": shop.id,
                        "shop_name": shop.shop_name,
                        "shop_slug": shop.shop_slug,
                        "description": shop.description,
                        "categories": [
                            {
                                "id": sc.category.id,
                                "name": sc.category.name,
                                "slug": sc.category.slug,
                            }
                            for sc in shop.categories
                        ],
                        "total_rating": shop.total_rating,
                        "total_raters": shop.total_raters,
                        "average_rating": shop.total_rating / shop.total_raters
                        if shop.total_raters > 0
                        else 0,
                        "user": {
                            "id": shop.user.id,
                            "username": shop.user.username,
                            "profile_picture": shop.user.profile_picture,
                        },
                    }
                    for shop in trending_shops
                ]

        except Exception as e:
            logger.error(f"Failed to get trending shops: {str(e)}")
            return []

    @staticmethod
    def get_shop_categories():
        """Get all shop categories for filtering"""
        try:
            with session_scope() as session:
                categories = (
                    session.query(Category).join(SellerCategory).distinct().all()
                )

                return [
                    {"id": cat.id, "name": cat.name, "slug": cat.slug}
                    for cat in categories
                ]

        except Exception as e:
            logger.error(f"Failed to get shop categories: {str(e)}")
            return []

    @staticmethod
    def _get_primary_product_image(product):
        """Safely resolve the primary image URL for a product"""
        if not getattr(product, "images", None):
            return None

        # Prefer featured images before falling back to sort order
        sorted_images = sorted(
            product.images,
            key=lambda img: (
                not getattr(img, "is_featured", False),
                getattr(img, "sort_order", 0)
                if getattr(img, "sort_order", None) is not None
                else 0,
            ),
        )

        for image in sorted_images:
            media = getattr(image, "media", None)
            if not media or getattr(media, "is_deleted", False):
                continue

            # Try responsive variants first, then fall back to original asset
            url_candidates = []
            if hasattr(media, "get_best_variant_for_screen"):
                url_candidates.extend(
                    [
                        media.get_best_variant_for_screen("desktop"),
                        media.get_best_variant_for_screen("mobile"),
                    ]
                )

            if hasattr(media, "get_url"):
                url_candidates.append(media.get_url(MediaVariantType.THUMBNAIL))
                url_candidates.append(media.get_url())

            # Finally, fall back to storage key when URL generation fails
            url_candidates.append(getattr(media, "storage_key", None))

            for url in url_candidates:
                if url:
                    return url

        return None

    @staticmethod
    def _get_shop_stats(shop_id):
        """Get shop statistics"""
        try:
            with session_scope() as session:
                # Get product count
                product_count = (
                    session.query(Product)
                    .filter(
                        Product.seller_id == shop_id,
                        Product.status == Product.Status.ACTIVE,
                    )
                    .count()
                )

                # Get post count
                shop_user = session.query(Seller).filter(Seller.id == shop_id).first()
                if not shop_user:
                    return {
                        "product_count": 0,
                        "post_count": 0,
                        "follower_count": 0,
                    }

                post_count = (
                    session.query(Post)
                    .filter(
                        Post.user_id == shop_user.user_id,
                        Post.status == PostStatus.ACTIVE,
                    )
                    .count()
                )

                # Get follower count - fix type mismatch
                # shop_id is integer, but followee_id is string (user_id)

                follower_count = (
                    session.query(Follow)
                    .filter(
                        Follow.followee_id == shop_user.user_id,
                        # Follow.is_active == True
                    )
                    .count()
                )

                return {
                    "product_count": product_count,
                    "post_count": post_count,
                    "follower_count": follower_count,
                }

        except Exception as e:
            logger.error(f"Failed to get shop stats: {str(e)}")
            return {
                "product_count": 0,
                "post_count": 0,
                "follower_count": 0,
            }

    @staticmethod
    def _is_followed_by_user(shop_user_id, user_id):
        """Check if user follows this shop"""
        try:
            with session_scope() as session:
                follow = (
                    session.query(Follow)
                    .filter(
                        Follow.follower_id == user_id,
                        Follow.followee_id == shop_user_id,
                        # Follow.is_active == True
                    )
                    .first()
                )
                return follow is not None

        except Exception as e:
            logger.error(f"Failed to check follow status: {str(e)}")
            return False


class SellerStartCardsService:
    """Service for managing seller onboarding/start cards"""

    @staticmethod
    def get_seller_start_cards(seller_id: int) -> Dict[str, Any]:
        """
        Get actionable start cards for seller onboarding with completion status.

        Returns cards with title, description, CTA, and completion state.
        Efficient for dashboard load with single DB session.
        """
        try:
            with session_scope() as session:
                # Get seller and user data in one query
                seller = (
                    session.query(Seller)
                    .options(joinedload(Seller.user))
                    .filter(Seller.id == seller_id)
                    .first()
                )

                if not seller:
                    raise NotFoundError("Seller not found")

                user = seller.user

                # Batch all completion checks in one session
                cards_data = SellerStartCardsService._compute_card_completion(
                    session, seller, user
                )

                return {
                    "items": cards_data,
                    "metadata": {
                        "seller_id": seller_id,
                        "generated_at": datetime.utcnow().isoformat(),
                    },
                }

        except Exception as e:
            logger.error(f"Failed to get seller start cards: {str(e)}")
            raise APIError("Failed to get seller start cards", 500)

    @staticmethod
    def _compute_card_completion(
        session, seller: Seller, user: User
    ) -> List[Dict[str, Any]]:
        """Compute completion status for all start cards"""

        # Card 1: Profile Setup
        profile_setup_completed = bool(
            seller.shop_name and seller.description and user.profile_picture
        )

        # Card 2: Add First Product
        product_count = (
            session.query(Product)
            .filter(
                Product.seller_id == seller.id, Product.status == Product.Status.ACTIVE
            )
            .count()
        )
        add_first_product_completed = product_count > 0

        # Card 3: Verify Email
        verify_email_completed = user.email_verified

        # Card 4: Fulfill Pending Orders
        pending_orders_count = (
            session.query(OrderItem)
            .filter(
                OrderItem.seller_id == seller.id,
                OrderItem.status == OrderItem.Status.PENDING,
            )
            .count()
        )
        fulfill_pending_orders_completed = pending_orders_count == 0

        # Card 5: Publish First Post
        post_count = (
            session.query(Post)
            .filter(Post.user_id == user.id, Post.status == PostStatus.ACTIVE)
            .count()
        )
        publish_first_post_completed = post_count > 0

        return [
            {
                "key": "profile_setup",
                "title": "Complete Your Profile",
                "description": "Add your shop name, description, and profile picture to build trust with customers.",
                "cta": {"label": "Complete Profile", "href": PROFILE_SETUP_HREF},
                "completed": profile_setup_completed,
                "progress": {
                    "current": sum(
                        [
                            bool(seller.shop_name),
                            bool(seller.description),
                            bool(user.profile_picture),
                        ]
                    ),
                    "target": 3,
                },
            },
            {
                "key": "add_first_product",
                "title": "Add Your First Product",
                "description": "Start selling by adding your first product to your shop.",
                "cta": {"label": "Add Product", "href": ADD_FIRST_PRODUCT_HREF},
                "completed": add_first_product_completed,
                "progress": {"current": product_count, "target": 1},
            },
            {
                "key": "verify_email",
                "title": "Verify Your Email",
                "description": "Verify your email address to secure your account and receive important updates.",
                "cta": {"label": "Verify Email", "href": VERIFY_EMAIL_HREF},
                "completed": verify_email_completed,
            },
            {
                "key": "fulfill_pending_orders",
                "title": "Fulfill Pending Orders",
                "description": f"You have {pending_orders_count} pending orders waiting to be processed.",
                "cta": {"label": "View Orders", "href": VIEW_ORDERS_HREF},
                "completed": fulfill_pending_orders_completed,
                "progress": {"current": pending_orders_count, "target": 0},
            },
            {
                "key": "publish_first_post",
                "title": "Engage Your Audience",
                "description": "Publish your first social post to connect with customers and showcase your products.",
                "cta": {"label": "Create Post", "href": CREATE_POST_HREF},
                "completed": publish_first_post_completed,
                "progress": {"current": post_count, "target": 1},
            },
        ]


class SellerAnalyticsService:
    """Service for seller analytics and graph data"""

    @staticmethod
    def get_seller_analytics_overview(
        seller_id: int, window_days: int = 30
    ) -> Dict[str, Any]:
        """
        Get quick overview metrics for seller dashboard header.

        Returns revenue, orders, views, and conversion rate for the specified window.
        """
        try:
            cache_key = f"seller:{seller_id}:analytics:overview:{window_days}"

            # Try cache first
            cached_data = redis_client.get(cache_key)
            if cached_data:
                import json

                return json.loads(cached_data)

            with session_scope() as session:
                end_date = datetime.utcnow()
                start_date = end_date - timedelta(days=window_days)

                # Get seller's product IDs for view calculations
                product_ids = [
                    p.id
                    for p in session.query(Product.id)
                    .filter(Product.seller_id == seller_id)
                    .all()
                ]

                if not product_ids:
                    # New seller with no products
                    overview = {
                        "revenue_30d": 0.0,
                        "orders_30d": 0,
                        "views_30d": 0,
                        "conversion_30d": 0.0,
                    }
                else:
                    # Revenue and orders from OrderItem
                    revenue_result = (
                        session.query(func.sum(OrderItem.price * OrderItem.quantity))
                        .filter(
                            OrderItem.seller_id == seller_id,
                            OrderItem.created_at >= start_date,
                            OrderItem.created_at <= end_date,
                        )
                        .scalar()
                    )

                    orders_result = (
                        session.query(func.count(OrderItem.id))
                        .filter(
                            OrderItem.seller_id == seller_id,
                            OrderItem.created_at >= start_date,
                            OrderItem.created_at <= end_date,
                        )
                        .scalar()
                    )

                    # Views from ProductView
                    views_result = (
                        session.query(func.count(ProductView.id))
                        .filter(
                            ProductView.product_id.in_(product_ids),
                            ProductView.viewed_at >= start_date,
                            ProductView.viewed_at <= end_date,
                        )
                        .scalar()
                    )

                    # Calculate conversion rate
                    conversion_rate = 0.0
                    if views_result and views_result > 0:
                        conversion_rate = round(
                            (orders_result or 0) / views_result * 100, 2
                        )

                    overview = {
                        "revenue_30d": float(revenue_result or 0),
                        "orders_30d": orders_result or 0,
                        "views_30d": views_result or 0,
                        "conversion_30d": conversion_rate,
                    }

                # Cache for 5 minutes
                import json

                redis_client.setex(cache_key, 300, json.dumps(overview))

                return overview

        except Exception as e:
            logger.error(f"Failed to get seller analytics overview: {str(e)}")
            raise APIError("Failed to get seller analytics overview", 500)

    @staticmethod
    def get_seller_analytics_timeseries(
        seller_id: int,
        metric: str,
        bucket: str,
        start_date: datetime,
        end_date: datetime,
    ) -> Dict[str, Any]:
        """
        Get time-bucketed analytics data for seller graphs.

        Args:
            seller_id: Seller ID
            metric: 'sales', 'orders', 'views', 'conversion'
            bucket: 'day', 'week', 'month'
            start_date: Start date for the series
            end_date: End date for the series
        """
        try:
            # Validate inputs
            valid_metrics = ["sales", "orders", "views", "conversion"]
            valid_buckets = ["day", "week", "month"]

            if metric not in valid_metrics:
                raise ValidationError(
                    f"Invalid metric. Must be one of: {valid_metrics}"
                )
            if bucket not in valid_buckets:
                raise ValidationError(
                    f"Invalid bucket. Must be one of: {valid_buckets}"
                )

            cache_key = f"seller:{seller_id}:analytics:{metric}:{bucket}:{start_date.date()}:{end_date.date()}"

            # Try cache first
            cached_data = redis_client.get(cache_key)
            if cached_data:
                import json

                return json.loads(cached_data)

            with session_scope() as session:
                # Get seller's product IDs for view calculations
                product_ids = [
                    p.id
                    for p in session.query(Product.id)
                    .filter(Product.seller_id == seller_id)
                    .all()
                ]

                if not product_ids and metric in ["views", "conversion"]:
                    # Return empty series for new sellers
                    result = {
                        "metric": metric,
                        "bucket": bucket,
                        "series": [],
                        "totals": {"value": 0, "count": 0},
                    }
                else:
                    series_data = SellerAnalyticsService._build_timeseries_data(
                        session,
                        seller_id,
                        product_ids,
                        metric,
                        bucket,
                        start_date,
                        end_date,
                    )

                    result = {
                        "metric": metric,
                        "bucket": bucket,
                        "series": series_data["series"],
                        "totals": series_data["totals"],
                    }

                # Cache for 5 minutes
                import json

                redis_client.setex(cache_key, 300, json.dumps(result))

                return result

        except Exception as e:
            logger.error(f"Failed to get seller analytics timeseries: {str(e)}")
            raise APIError("Failed to get seller analytics timeseries", 500)

    @staticmethod
    def _build_timeseries_data(
        session,
        seller_id: int,
        product_ids: List[str],
        metric: str,
        bucket: str,
        start_date: datetime,
        end_date: datetime,
    ) -> Dict[str, Any]:
        """Build time-bucketed data for the specified metric"""

        # Map bucket to SQL date truncation
        bucket_map = {"day": "day", "week": "week", "month": "month"}

        if metric == "sales":
            # Revenue over time
            query = (
                session.query(
                    func.date_trunc(bucket_map[bucket], OrderItem.created_at).label(
                        "bucket_start"
                    ),
                    func.sum(OrderItem.price * OrderItem.quantity).label("value"),
                )
                .filter(
                    OrderItem.seller_id == seller_id,
                    OrderItem.created_at >= start_date,
                    OrderItem.created_at <= end_date,
                )
                .group_by(func.date_trunc(bucket_map[bucket], OrderItem.created_at))
                .order_by("bucket_start")
            )

        elif metric == "orders":
            # Order count over time
            query = (
                session.query(
                    func.date_trunc(bucket_map[bucket], OrderItem.created_at).label(
                        "bucket_start"
                    ),
                    func.count(OrderItem.id).label("value"),
                )
                .filter(
                    OrderItem.seller_id == seller_id,
                    OrderItem.created_at >= start_date,
                    OrderItem.created_at <= end_date,
                )
                .group_by(func.date_trunc(bucket_map[bucket], OrderItem.created_at))
                .order_by("bucket_start")
            )

        elif metric == "views":
            # Product views over time
            query = (
                session.query(
                    func.date_trunc(bucket_map[bucket], ProductView.viewed_at).label(
                        "bucket_start"
                    ),
                    func.count(ProductView.id).label("value"),
                )
                .filter(
                    ProductView.product_id.in_(product_ids),
                    ProductView.viewed_at >= start_date,
                    ProductView.viewed_at <= end_date,
                )
                .group_by(func.date_trunc(bucket_map[bucket], ProductView.viewed_at))
                .order_by("bucket_start")
            )

        elif metric == "conversion":
            # Conversion rate over time (orders/views)
            # This is more complex - we need to join views and orders by time bucket
            views_query = (
                session.query(
                    func.date_trunc(bucket_map[bucket], ProductView.viewed_at).label(
                        "bucket_start"
                    ),
                    func.count(ProductView.id).label("views"),
                )
                .filter(
                    ProductView.product_id.in_(product_ids),
                    ProductView.viewed_at >= start_date,
                    ProductView.viewed_at <= end_date,
                )
                .group_by(func.date_trunc(bucket_map[bucket], ProductView.viewed_at))
                .subquery()
            )

            orders_query = (
                session.query(
                    func.date_trunc(bucket_map[bucket], OrderItem.created_at).label(
                        "bucket_start"
                    ),
                    func.count(OrderItem.id).label("orders"),
                )
                .filter(
                    OrderItem.seller_id == seller_id,
                    OrderItem.created_at >= start_date,
                    OrderItem.created_at <= end_date,
                )
                .group_by(func.date_trunc(bucket_map[bucket], OrderItem.created_at))
                .subquery()
            )

            # Join views and orders, calculate conversion rate
            query = (
                session.query(
                    func.coalesce(
                        views_query.c.bucket_start, orders_query.c.bucket_start
                    ).label("bucket_start"),
                    func.coalesce(views_query.c.views, 0).label("views"),
                    func.coalesce(orders_query.c.orders, 0).label("orders"),
                    func.case(
                        (
                            func.coalesce(views_query.c.views, 0) > 0,
                            func.round(
                                func.coalesce(orders_query.c.orders, 0)
                                * 100.0
                                / func.coalesce(views_query.c.views, 0),
                                2,
                            ),
                        ),
                        else_=0,
                    ).label("value"),
                )
                .outerjoin(
                    orders_query,
                    views_query.c.bucket_start == orders_query.c.bucket_start,
                )
                .outerjoin(
                    views_query,
                    orders_query.c.bucket_start == views_query.c.bucket_start,
                )
                .order_by("bucket_start")
            )

        # Execute query and format results
        results = query.all()

        series = []
        total_value = 0
        total_count = 0

        for row in results:
            bucket_start = row.bucket_start.isoformat() if row.bucket_start else None
            value = float(row.value) if row.value is not None else 0.0

            series.append({"bucket_start": bucket_start, "value": value})

            total_value += value
            total_count += 1

        return {
            "series": series,
            "totals": {"value": total_value, "count": total_count},
        }
