# python imports
import random
import logging

# package imports
from sqlalchemy.orm import joinedload
from sqlalchemy import func

# projects imports
from external.redis import redis_client
from external.database import db
from app.libs.session import session_scope
from app.libs.errors import AuthError, NotFoundError, APIError
from app.libs.pagination import Paginator

from app.products.models import Product
from app.socials.models import Post, PostStatus, Follow

# app imports
from .models import User, Buyer, Seller, UserAddress, SellerVerificationStatus
from .constants import RESERVED_USERNAMES

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

            # Check if user is active
            if not user.is_active:
                raise AuthError("Account is deactivated")

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
                        "category": shop.category,
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
                recent_posts = (
                    session.query(Post)
                    .filter(Post.seller_id == shop_id, Post.status == PostStatus.ACTIVE)
                    .order_by(Post.created_at.desc())
                    .limit(6)
                    .all()
                )

                shop_data = {
                    "id": shop.id,
                    "shop_name": shop.shop_name,
                    "shop_slug": shop.shop_slug,
                    "description": shop.description,
                    "category": shop.category,
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
                            "image": product.images[0].url if product.images else None,
                        }
                        for product in recent_products
                    ],
                    "recent_posts": [
                        {
                            "id": post.id,
                            "caption": post.caption,
                            "media": [
                                {"url": m.media_url, "type": m.media_type}
                                for m in post.media
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
                        "category": shop.category,
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
                    session.query(Seller.category)
                    .filter(Seller.category.isnot(None))
                    .distinct()
                    .all()
                )

                return [category[0] for category in categories if category[0]]

        except Exception as e:
            logger.error(f"Failed to get shop categories: {str(e)}")
            return []

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
                post_count = (
                    session.query(Post)
                    .filter(Post.seller_id == shop_id, Post.status == PostStatus.ACTIVE)
                    .count()
                )

                # Get follower count - fix type mismatch
                # shop_id is integer, but followee_id is string (user_id)
                shop_user = session.query(Seller).filter(Seller.id == shop_id).first()
                if not shop_user:
                    return {
                        "product_count": 0,
                        "post_count": 0,
                        "follower_count": 0,
                    }

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
