def parse_dict(product, images):
    """
    Parses and structures product data and associated images for API responses.

    Args:
        product (Product): The product object containing information such as name, price, description, etc.
        images (list[ImageNameStore]): A list of image objects related to the product.

    Returns:
        dict: A dictionary containing parsed information about the product, including the images.
    """
    return {
        "seller_id": product.seller_id,
        "product_name": product.name,
        "description": product.description,
        "product_price": product.price,
        "quantity": product.stock_quantity,
        "category": product.category,
        "product_id": product.product_id,
        "product_images": [image.image_name for image in images]
        if images is not None
        else [],
    }
