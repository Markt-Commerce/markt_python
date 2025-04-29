from flask_smorest import Blueprint
from flask.views import MethodView
from flask import abort, request

from ..schemas import FavoriteSchema
from ..models import Favorite, ImageNameStore, User, Seller
from ..utils import parse_favorite

favorite_bp = Blueprint(
    "favorites",
    "favorite",
    description="Endpoint for all API calls related to buyer favorites",
    url_prefix="/favorites",
)


@favorite_bp.route("/new")
class AddFavorite(MethodView):
    @favorite_bp.arguments(FavoriteSchema)
    @favorite_bp.response(201, description="favorite created successfully")
    def post(self, favorite_data):
        try:
            favorite = Favorite(
                buyer_id=favorite_data["buyer_id"],
                favorite_item_id=favorite_data["favorite_item_id"],
                favorite_type=favorite_data["favorite_type"],
            )
            favorite.save_to_db()
            return {"message": "favorite created successfully."}, 201
        except Exception:
            abort(500, "could not save favorite")


@favorite_bp.route("/<buyer_id>")
class BuyerFavorites(MethodView):
    @favorite_bp.response(201, FavoriteSchema)
    def get(self, buyer_id):
        try:
            buyer_favorite_list = []
            for favorites in Favorite.get_all_buyer_favorites(buyer_id):
                if favorites.favorite_type == "seller":
                    seller = Seller(id=favorites.favorite_item_id)  # TODO: TBD
                    buyer_favorite_list.append(
                        parse_favorite(favorite=favorites, image=seller.profile_picture)
                    )
                elif favorites.favorite_type == "product":
                    buyer_favorite_list.append(
                        parse_favorite(
                            favorite=favorites,
                            image=ImageNameStore.getproductthumbnail(
                                product_id=favorites.favorite_item_id
                            ),
                        )
                    )
            return buyer_favorite_list
        except Exception:
            abort(404, "not found")

    @favorite_bp.response(201, FavoriteSchema)
    def delete(self, buyer_id):
        try:
            return Favorite.delete_all_buyer_favorites(buyer_id)
        except Exception:
            abort(404, "not found")


@favorite_bp.route("/<favorite_id>")
class GetFavorite(MethodView):
    @favorite_bp.arguments(FavoriteSchema)
    @favorite_bp.response(201, FavoriteSchema)
    def delete(self, favorite_id):
        try:
            favorite = Favorite(id=favorite_id)
            favorite.delete_from_db()
        except Exception:
            abort(404, "not found")
