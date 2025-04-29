def parse_requests(request, buyer, user_details):
    """
    Parses and structures product request data for API responses.

    Args:
        request (BuyerRequest): The product request object containing details like description, category, etc.
        buyer (Buyer): The buyer object associated with the request.
        user_details (User): The user's address details, including location and profile image.

    Returns:
        dict: A dictionary containing parsed information about the buyer, request, and user details.
    """
    return {
        "buyer_name": buyer.username,
        "city": user_details.get_user_location_data["city"],
        "state": user_details.get_user_location_data["state"],
        "profile_image": user_details.profile_image,
        "query_id": request.unique_id,
        "message": request.product_description,
        "buyer_id": request.buyer_id,
        "category": request.category,
        "stale_time": request.created_at,
    }
