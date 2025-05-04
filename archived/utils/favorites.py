def parse_favorite(favorite, image):
    return {
        "id": favorite.id,
        "buyer_id": favorite.buyer_id,
        "favorite_item_id": favorite.favorite_item_id,
        "favorite_type": favorite.favorite_type,
        "thumbnail": image,
    }
