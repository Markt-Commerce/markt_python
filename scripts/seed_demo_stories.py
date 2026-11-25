"""Extra demo state for the feature videos, layered on scripts/seed_demo.py.

Each story needs something the base seed does not have:

  shops near you    shop banners and logos
  communities       five niches with images, members and posts
  buy & sell        Ada holds both roles, and has a paid order waiting for her
  better price      a pending chat discount from Ada to Temi
  share the ride    batching on, neighbours' shared orders heading to UI

Same rules as the base seed: fixed ids, idempotent, everything a take can
change is put back. Database work happens inside seed_demo's session (see
reset_stories / seed_stories); the order and discount steps go through the
real API afterwards, so every row they create is one the app would write.
"""

import os
from datetime import datetime, timedelta

from seed_demo import (
    BUYERS,
    DEMO_BUYER_ID,
    DEMO_PASSWORD,
    MEDIA_DIR,
    SELLERS,
    _font,
    _media_url,
)

ADA = "USR_DMO_S001"
BISI = "USR_DMO_S003"

# Shop logos: the shops are fictional, so their marks are drawn here (a
# monogram on the shop's colour) rather than photographed. A real logo at
# demo/images/avatars/<username>.* wins over these.
SHOP_LOGOS = {
    "adasankara": ("AA", (142, 31, 91)),
    "tobigadgets": ("TG", (29, 53, 87)),
    "mamabisi": ("MB", (45, 106, 79)),
    "chinedukicks": ("CK", (24, 24, 24)),
    "halimaglow": ("HG", (181, 101, 29)),
}

# (id, name, slug, description, category slug, owner, members, posts, posts in it)
NICHES = [
    (
        "NCH_DMO_0001",
        "UI Campus Style",
        "ui-campus-style",
        "Ankara, adire, thrift and everything in between -- what UI is wearing "
        "this week.",
        "fashion",
        ADA,
        1240,
        38,
        ["PST_DMO_0001", "PST_DMO_0006"],
    ),
    (
        "NCH_DMO_0002",
        "Ibadan Foodies",
        "ibadan-foodies",
        "Where to eat, what to cook, and who has the freshest foodstuff in " "Bodija.",
        "food-beverages",
        BISI,
        860,
        52,
        ["PST_DMO_0002"],
    ),
    (
        "NCH_DMO_0003",
        "Gadget Plug Ibadan",
        "gadget-plug",
        "Phones, power banks and laptops. Honest prices, tested in front of " "you.",
        "electronics",
        "USR_DMO_S002",
        530,
        27,
        ["PST_DMO_0003"],
    ),
    (
        "NCH_DMO_0004",
        "Thrift Gang Agbowo",
        "thrift-gang",
        "Saturday bales, clean kicks, vintage finds. Show us your best cop.",
        "fashion",
        "USR_DMO_S004",
        410,
        19,
        ["PST_DMO_0004"],
    ),
    (
        "NCH_DMO_0005",
        "Natural Glow Club",
        "natural-glow",
        "Shea, black soap and oils that actually work. Routines, not hype.",
        "health-beauty",
        "USR_DMO_S005",
        690,
        31,
        ["PST_DMO_0005"],
    ),
]
# Temi is already in these; UI Campus Style is the one she joins on camera.
TEMI_NICHES = {"NCH_DMO_0002", "NCH_DMO_0003"}

# Ada as a buyer too (for the switch-role story).
ADA_BUYER = {
    "name": "Adaeze Okafor",
    "street": "15 Awolowo Avenue, Bodija",
    "lat": 7.4372,
    "lng": 3.9171,
    "area": "Bodija, Ibadan",
}

# Neighbours whose shared-delivery orders a take can join: delivered to UI,
# from Mama Bisi (Bodija market), so they group into one run.
BATCH_NEIGHBOURS = [
    (
        "USR_DMO_B003",
        "PRD_DMO_0009",
        "Mellanby Hall, University of Ibadan",
        7.4450,
        3.8990,
    ),
    ("USR_DMO_B002", "PRD_DMO_0010", "Kuti Hall, University of Ibadan", 7.4486, 3.8940),
]
STORY_WALLET = 120000  # for the buyers who place orders here


def _shop_logo(username):
    from PIL import Image, ImageDraw

    letters, colour = SHOP_LOGOS[username]
    size = 400
    img = Image.new("RGB", (size, size), colour)
    draw = ImageDraw.Draw(img)
    draw.text(
        (size / 2, size / 2 + 6), letters, fill="white", font=_font(170), anchor="mm"
    )
    out_dir = os.path.join(MEDIA_DIR, "seed", "logos")
    os.makedirs(out_dir, exist_ok=True)
    img.save(os.path.join(out_dir, f"{username}.png"))
    return f"seed/logos/{username}.png"


# ---------------------------------------------------------------------------
# Database (inside seed_demo's session)
# ---------------------------------------------------------------------------


def reset_stories(session):
    """Undo story rows before seed_demo deletes the seed media they point at."""
    from sqlalchemy import text

    session.execute(
        text(
            "UPDATE niches SET image_id = NULL, banner_id = NULL "
            "WHERE id LIKE 'NCH_DMO_%'"
        )
    )
    session.execute(text("DELETE FROM niche_posts WHERE niche_id LIKE 'NCH_DMO_%'"))
    session.execute(
        text(
            "DELETE FROM niche_memberships WHERE niche_id LIKE 'NCH_DMO_%' "
            "OR user_id LIKE 'USR_DMO_%'"
        )
    )
    session.execute(
        text("DELETE FROM niche_categories WHERE niche_id LIKE 'NCH_DMO_%'")
    )
    session.flush()


def seed_stories(session, *, add_media, ago, categories, upsert, stage_image):
    """`stage_image` is passed in rather than imported so placeholders are
    reported by the running seed, not a second copy of its module."""
    from app.categories.models import NicheCategory
    from app.location.models import BrowseLocation
    from app.socials.models import (
        Niche,
        NicheMembership,
        NicheMembershipRole,
        NichePost,
        NicheStatus,
        NicheVisibility,
        PostStatus,
    )
    from app.users.addresses import SavedAddress
    from app.users.models import Buyer, RefundPreference, Seller, User

    # --- shops near you: banners and logos --------------------------------
    for s in SELLERS:
        user = session.get(User, s["id"])
        seller = session.query(Seller).filter_by(user_id=user.id).one()
        if not os.path.isfile(
            os.path.join(MEDIA_DIR, "..", "images", "avatars", s["username"] + ".jpg")
        ):
            user.profile_picture = _media_url(_shop_logo(s["username"]))
        key, *_ = stage_image("banners", s["username"], s["shop_name"])
        seller.banner_url = _media_url(key)

    # --- communities -------------------------------------------------------
    everyone = [s["id"] for s in SELLERS] + [b["id"] for b in BUYERS]
    for i, (nid, name, slug, desc, cat, owner, members, posts, post_ids) in enumerate(
        NICHES
    ):
        avatar = add_media(owner, "niches", f"{slug}-avatar", name)
        banner = add_media(owner, "niches", f"{slug}-banner", name)
        upsert(
            session,
            Niche,
            nid,
            name=name,
            slug=slug,
            description=desc,
            status=NicheStatus.ACTIVE,
            visibility=NicheVisibility.PUBLIC,
            allow_buyer_posts=True,
            allow_seller_posts=True,
            require_approval=False,
            image_id=avatar.id,
            banner_id=banner.id,
            member_count=members,
            post_count=posts,
            tags=[cat],
            rules=["Be kind.", "No fake listings."],
            created_at=ago(60 * 24 * (200 - i * 30)),
        )
        session.flush()
        session.add(
            NicheCategory(niche_id=nid, category_id=categories[cat].id, is_primary=True)
        )
        for uid in everyone:
            if uid == DEMO_BUYER_ID and nid not in TEMI_NICHES:
                continue
            session.add(
                NicheMembership(
                    niche_id=nid,
                    user_id=uid,
                    is_active=True,
                    is_banned=False,
                    role=(
                        NicheMembershipRole.OWNER
                        if uid == owner
                        else NicheMembershipRole.MEMBER
                    ),
                )
            )
        for j, pid in enumerate(post_ids):
            session.add(
                NichePost(
                    niche_id=nid,
                    post_id=pid,
                    status=PostStatus.ACTIVE,
                    is_approved=True,
                    is_pinned=(j == 0),
                )
            )

    # --- buy & sell: Ada holds both roles ---------------------------------
    ada = session.get(User, ADA)
    ada.is_buyer = True
    b = ADA_BUYER
    address = {
        "recipient_name": b["name"],
        "street_address": b["street"],
        "city": "Ibadan",
        "state": "Oyo",
        "country": "Nigeria",
        "latitude": b["lat"],
        "longitude": b["lng"],
    }
    buyer = session.query(Buyer).filter_by(user_id=ADA).one_or_none()
    if buyer is None:
        buyer = Buyer(user_id=ADA)
        session.add(buyer)
    buyer.buyername, buyer.shipping_address, buyer.is_active = b["name"], address, True
    session.query(SavedAddress).filter_by(user_id=ADA).delete()
    session.add(
        SavedAddress(
            user_id=ADA,
            label="Home",
            is_default=True,
            formatted_address=f"{b['street']}, Ibadan, Oyo",
            latitude=b["lat"],
            longitude=b["lng"],
            city="Ibadan",
            state="Oyo",
            contact_name=b["name"],
        )
    )
    bl = session.query(BrowseLocation).filter_by(user_id=ADA).one_or_none()
    if bl is None:
        bl = BrowseLocation(user_id=ADA, latitude=b["lat"], longitude=b["lng"])
        session.add(bl)
    bl.latitude, bl.longitude, bl.label = b["lat"], b["lng"], b["area"]
    bl.state, bl.lga, bl.updated_at_utc = "Oyo", "Ibadan North", datetime.utcnow()

    # --- share the ride: refunds land in the wallet, instantly -------------
    for uid in [DEMO_BUYER_ID] + [n[0] for n in BATCH_NEIGHBOURS]:
        row = session.query(Buyer).filter_by(user_id=uid).one()
        row.refund_preference = RefundPreference.WALLET.value
    session.flush()


# ---------------------------------------------------------------------------
# Through the API (after the seed has committed)
# ---------------------------------------------------------------------------


def _api(api_base):
    import requests

    def login(email, role):
        r = requests.post(
            f"{api_base}/users/login",
            timeout=30,
            json={"email": email, "password": DEMO_PASSWORD, "account_type": role},
        )
        r.raise_for_status()
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    def items(resp):
        body = resp.json()
        if isinstance(body, list):
            return body
        for key in ("items", "allocations", "discounts", "rooms", "orders"):
            if isinstance(body.get(key), list):
                return body[key]
        return []

    return requests, login, items


def _email(uid):
    return next(p["email"] for p in SELLERS + BUYERS if p["id"] == uid)


def _place_order(api_base, buyer_uid, product_id, street, lat, lng, *, batch=False):
    """Cart -> delivery quote -> checkout -> wallet, as the app does it."""
    import uuid

    requests, login, _ = _api(api_base)
    h = login(_email(buyer_uid), "buyer")
    person = next((p for p in BUYERS if p["id"] == buyer_uid), None)
    name = person["name"] if person else ADA_BUYER["name"]
    requests.post(
        f"{api_base}/cart/add",
        headers=h,
        timeout=30,
        json={"product_id": product_id, "quantity": 1},
    ).raise_for_status()
    seller = requests.get(
        f"{api_base}/products/{product_id}", headers=h, timeout=30
    ).json()["seller"]
    seller_id = seller.get("id") or seller.get("seller_id")
    q = requests.post(
        f"{api_base}/delivery/quote",
        headers=h,
        timeout=30,
        json={
            "seller_id": seller_id,
            "dropoff_latitude": lat,
            "dropoff_longitude": lng,
            "item_count": 1,
        },
    )
    q.raise_for_status()
    address = {
        "recipient_name": name,
        "street_address": street,
        "city": "Ibadan",
        "state": "Oyo",
        "country": "Nigeria",
        "latitude": lat,
        "longitude": lng,
    }
    r = requests.post(
        f"{api_base}/cart/checkout",
        headers=h,
        timeout=30,
        json={
            "shipping_address": address,
            "billing_address": address,
            "use_saved_address": False,
            "seller_id": seller_id,
            "delivery_quote_id": q.json()["id"],
            "batch_opt_in": batch,
            "idempotency_key": f"demo-story-{uuid.uuid4()}",
        },
    )
    r.raise_for_status()
    order = r.json()
    p = requests.post(
        f"{api_base}/payments/create",
        headers=h,
        timeout=30,
        json={
            "order_id": order["order_id"],
            "method": "wallet",
            "amount": order["total"],
            "idempotency_key": f"demo-story-pay-{order['order_id']}",
        },
    )
    p.raise_for_status()
    return order["order_id"]


def ensure_pending_allocation(api_base):
    """A fresh paid order for Ada's shop, waiting for her to accept.

    A seller has three minutes to answer, and the card shows "respond by
    HH:MM". So rather than keep an old request (whose deadline has passed by
    the time anyone records), accept whatever is waiting -- it reads as Ada's
    order history -- and place a new one. Seed right before the take.
    """
    requests, login, items = _api(api_base)
    ada = login(_email(ADA), "seller")
    for a in items(
        requests.get(f"{api_base}/fulfilment/allocations", headers=ada, timeout=30)
    ):
        if str(a.get("status", "")).lower() == "awaiting_seller":
            requests.post(
                f"{api_base}/fulfilment/allocations/{a['id']}/accept",
                headers=ada,
                timeout=30,
            )
    ife = next(b for b in BUYERS if b["id"] == "USR_DMO_B002")
    return _place_order(
        api_base, ife["id"], "PRD_DMO_0003", ife["street"], ife["lat"], ife["lng"]
    )


def ensure_discount_offer(api_base):
    """Ada offers Temi 10% on the shirt in their chat (better-price story)."""
    requests, login, items = _api(api_base)
    ada = login(_email(ADA), "seller")
    rooms = items(
        requests.get(
            f"{api_base}/chats/rooms?page=1&per_page=50", headers=ada, timeout=30
        )
    )
    room = next(
        r for r in rooms if (r.get("other_user") or {}).get("username") == "temi_adeoye"
    )
    existing = items(
        requests.get(
            f"{api_base}/chats/rooms/{room['id']}/discounts", headers=ada, timeout=30
        )
    )
    if any(str(d.get("status", "")).lower() == "pending" for d in existing):
        return room["id"], False
    r = requests.post(
        f"{api_base}/chats/rooms/{room['id']}/discounts",
        headers=ada,
        timeout=30,
        json={
            "discount_type": "percentage",
            "discount_value": 10,
            "expires_at": (datetime.utcnow() + timedelta(days=2)).isoformat(),
            "product_id": "PRD_DMO_0001",
            "discount_message": "For you, 10% off the star-print shirt",
        },
    )
    r.raise_for_status()
    return room["id"], True


def ensure_batch_neighbours(api_base):
    """Two neighbours' shared-delivery orders from Mama Bisi to UI, paid.

    A run needs company: these are the other orders Temi's take can share a
    rider with. Placed once; re-runs leave them alone until a run closes.
    """
    requests, login, items = _api(api_base)
    placed = []
    for uid, product_id, street, lat, lng in BATCH_NEIGHBOURS:
        h = login(_email(uid), "buyer")
        orders = items(
            requests.get(
                f"{api_base}/orders/?page=1&per_page=50", headers=h, timeout=30
            )
        )
        # The list does not carry batch_opt_in; this product, still open, is ours.
        open_batch = [
            o
            for o in orders
            if any(i.get("product_id") == product_id for i in o.get("items", []))
            and str(o.get("status", "")).lower() not in ("delivered", "cancelled")
        ]
        if not open_batch:
            placed.append(
                _place_order(api_base, uid, product_id, street, lat, lng, batch=True)
            )
    return placed


def story_wallets():
    """Buyers who place orders here need money in their wallets."""
    return [n[0] for n in BATCH_NEIGHBOURS] + ["USR_DMO_B002"]
