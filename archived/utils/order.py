def parse_unaccepted_orders(order, buyer, product, product_image):
    return {
        "order_id": order.order_id,
        "seller_id": order.seller_id,
        "product_quantity": order.quantity,
        "order_date": order.order_date,
        "product_name": product.name,
        "total_price": order.total_price,
        "product_id": order.product_id,
        "product_image": product_image,
        "buyer_id": order.buyer_id,
        "buyer_name": buyer.username,
    }


def parse_orders(order, seller, buyer, product, product_image):
    return {
        "order_id": order.order_id,
        "seller_id": order.seller_id,
        "product_quantity": order.quantity,
        "order_date": order.order_date,
        "product_name": product.name,
        "total_price": order.total_price,
        "product_id": order.product_id,
        "product_image": product_image,
        "buyer_id": order.buyer_id,
        "buyer_name": buyer.username,
    }


def parse_buyer_orders(order, seller, buyer, product, product_image):
    return {
        "order_id": order.order_id,
        "seller_id": order.seller_id,
        "product_quantity": order.quantity,
        "order_date": order.order_date,
        "product_name": product.name,
        "total_price": order.total_price,
        "product_id": order.product_id,
        "product_image": product_image,
        "buyer_id": order.buyer_id,
        "buyer_name": buyer.username,
        "seller_shopname": seller.shop_name,
        "order_status": order.order_status,
        "delivery_name": "",
        "delivery_id": "",
        "received_by_delivery": False,
    }


def parse_successful_orders(order, seller, buyer, product, product_image):
    return {
        "seller_id": order.seller_id,
        "product_name": product.name,
        "total_price": order.total_price,
        "product_quantity": order.quantity,
    }
