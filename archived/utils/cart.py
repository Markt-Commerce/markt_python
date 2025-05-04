# Jsonify cart and related info
def parse_cart(cart_item, image=None):
    return {
        "buyer_id": cart_item.buyer_id,
        "product_id": cart_item.product_id,
        "quantity": cart_item.quantity,
        "has_discount": cart_item.has_discount,
        "discount_price": cart_item.discount_price,
        "discount_percent": cart_item.discount_percent,
        "product_image": image.image_name if image else "",
    }
