"""What a product looked like when it was bought.

`OrderItem.price` has always been frozen at checkout. The name and the photo
were not -- the order screens read them live off the product, so a seller who
renamed a listing or swapped its photo after a sale changed what the buyer saw
in their own order history. Sellers can now change photos from the app, which
turns that from a curiosity into the classic bait-and-switch: sell the real
thing, swap the picture, ship the knockoff, and the receipt agrees with the
seller.

One helper rather than three copies, because the three places that build an
OrderItem must agree about what "what I bought" means.
"""

from typing import Any, Optional, Tuple


def product_image_url(product: Any) -> Optional[str]:
    """The product's first image, or None.

    Never raises: a missing thumbnail must not be able to fail a checkout.
    """
    try:
        images = getattr(product, "images", None) or []
        if not images:
            return None
        media = getattr(images[0], "media", None)
        return media.get_url() if media else None
    except Exception:
        return None


def product_snapshot(product: Any) -> Tuple[Optional[str], Optional[str]]:
    """(name, image_url) as they are right now, for freezing onto an order.

    A product that cannot be read gives (None, None) rather than raising. The
    read path falls back to the live product when the snapshot is empty, which
    is the same behaviour orders placed before this existed already get.
    """
    if product is None:
        return None, None
    name = getattr(product, "name", None)
    url = product_image_url(product)
    # The column is 500 wide and a signed URL can be longer; storing a
    # truncated URL would render a broken image, so store nothing instead.
    if url and len(url) > 500:
        url = None
    return name, url
