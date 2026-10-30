#!/usr/bin/env python
"""Seed a small, curated, camera-ready dataset for the product video.

Not test data and not bulk data: five believable Ibadan shops, a handful of
buyers, ~18 products, a few posts and chat threads -- enough that the feed,
a product page, the inbox and checkout all look alive on camera.

    MARKT_DEMO=1 python scripts/seed_demo.py

Run it through scripts/demo_up.sh, which sets MARKT_DEMO and the media
origin. It refuses to run without MARKT_DEMO=1 or with ENV=production,
because it deletes and recreates demo-owned rows.

Deterministic and idempotent:
  * Users, shops, products and posts have fixed ids (USR_DMO_*, PRD_DMO_*,
    PST_DMO_*) and are upserted.
  * Everything hanging off them that a recording can change -- images,
    likes, comments, follows, chat threads, the demo buyer's cart -- is
    deleted and recreated, so a re-run puts the screens back exactly.
  * Timestamps are offsets from "now", so "2h ago" reads the same on every
    take as long as you record soon after seeding.
  * Orders placed during a take are NOT undone; `demo_up.sh --fresh`
    rebuilds the database for that.

Images: nothing is downloaded or generated to look real. Each product names
an image key; the seed looks for demo/images/<key>.{jpg,jpeg,png,webp} and,
if it is missing, writes an obviously-placeholder tile and says so. Avatars
work the same way from demo/images/avatars/<username>.*, falling back to an
initials disc. See demo/images/README.md for the full list of keys.
"""

import os
import shutil
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMAGES_DIR = os.path.join(ROOT, "demo", "images")
MEDIA_DIR = os.path.join(ROOT, "demo", "media")
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")

DEMO_PASSWORD = "MarktDemo#2026"
BRAND = (233, 76, 42)  # #E94C2A

# ---------------------------------------------------------------------------
# The cast. Fictional people with ordinary Nigerian names; emails use the
# reserved example.com domain so nothing can ever be delivered to them.
# ---------------------------------------------------------------------------

SELLERS = [
    {
        "id": "USR_DMO_S001",
        "username": "adasankara",
        "email": "adaeze.okafor@example.com",
        "phone": "+2348000004501",
        "shop_name": "Ada's Ankara House",
        "description": "Ready-to-wear Ankara and Adire, cut and sewn in Bodija. "
        "Same-day delivery around Ibadan.",
        "market": "bodija-market",
        "lat": 7.4405,
        "lng": 3.9195,
        "street": "Shop 14, Bodija Market Road",
        "category": "fashion",
        "rating": (47, 10),
    },
    {
        "id": "USR_DMO_S002",
        "username": "tobigadgets",
        "email": "tobi.akinwale@example.com",
        "phone": "+2348000004502",
        "shop_name": "Tobi Gadgets",
        "description": "UK-used and brand-new phones, tested in front of you. "
        "Three months warranty on every phone.",
        "market": "ui-market",
        "lat": 7.4471,
        "lng": 3.8975,
        "street": "Shop 3, UI Shopping Complex",
        "category": "electronics",
        "rating": (93, 20),
    },
    {
        "id": "USR_DMO_S003",
        "username": "mamabisi",
        "email": "bisola.adeyemi@example.com",
        "phone": "+2348000004503",
        "shop_name": "Mama Bisi Foodstuff",
        "description": "Ofada rice, palm oil, egusi and fresh pepper -- "
        "straight from the farm to your kitchen.",
        "market": "bodija-market",
        "lat": 7.4392,
        "lng": 3.9210,
        "street": "Block C, Bodija Market",
        "category": "food-beverages",
        "rating": (144, 30),
    },
    {
        "id": "USR_DMO_S004",
        "username": "chinedukicks",
        "email": "chinedu.eze@example.com",
        "phone": "+2348000004504",
        "shop_name": "Chinedu Kicks & Thrift",
        "description": "Clean thrift sneakers and vintage denim. New bale "
        "every Saturday at Agbowo.",
        "market": "agbowo-market",
        "lat": 7.4462,
        "lng": 3.9141,
        "street": "12 Agbowo Shopping Complex",
        "category": "fashion",
        "rating": (66, 15),
    },
    {
        "id": "USR_DMO_S005",
        "username": "halimaglow",
        "email": "halima.bello@example.com",
        "phone": "+2348000004505",
        "shop_name": "Halima Glow",
        "description": "Raw shea butter, black soap and hair oils, made in "
        "small batches.",
        "market": "sango-market",
        "lat": 7.4241,
        "lng": 3.8988,
        "street": "7 Sango-Eleyele Road",
        "category": "health-beauty",
        "rating": (38, 8),
    },
]

# The account the recordings log in as, plus a few buyers who like and
# comment so the feed has life in it.
DEMO_BUYER_ID = "USR_DMO_B001"
BUYERS = [
    {
        "id": DEMO_BUYER_ID,
        "username": "temi_adeoye",
        "email": "temi@example.com",
        "phone": "+2348000004511",
        "name": "Temi Adeoye",
        "area": "University of Ibadan",
        "street": "Room B12, Queen Elizabeth II Hall, University of Ibadan",
        "lat": 7.4466,
        "lng": 3.8959,
    },
    {
        "id": "USR_DMO_B002",
        "username": "ifeoluwa.o",
        "email": "ifeoluwa@example.com",
        "phone": "+2348000004512",
        "name": "Ifeoluwa Ogunleye",
        "area": "Bodija, Ibadan",
        "street": "4 Awolowo Avenue, Bodija",
        "lat": 7.4380,
        "lng": 3.9180,
    },
    {
        "id": "USR_DMO_B003",
        "username": "musa_abdul",
        "email": "musa@example.com",
        "phone": "+2348000004513",
        "name": "Musa Abdullahi",
        "area": "University of Ibadan",
        "street": "Mellanby Hall, University of Ibadan",
        "lat": 7.4450,
        "lng": 3.8990,
    },
    {
        "id": "USR_DMO_B004",
        "username": "ngozi.c",
        "email": "ngozi@example.com",
        "phone": "+2348000004514",
        "name": "Ngozi Chukwu",
        "area": "Sango, Ibadan",
        "street": "22 Sango Road, Ibadan",
        "lat": 7.4230,
        "lng": 3.9000,
    },
]

# (id, seller id, name, price, compare_at, stock, category slug, image key,
#  description)
PRODUCTS = [
    (
        "PRD_DMO_0001",
        "USR_DMO_S001",
        "Ankara Star-Print Shirt",
        18500,
        22000,
        25,
        "fashion",
        "ankara-two-piece",
        "Golden-yellow Ankara with a red-and-navy star print, cut slim with a "
        "proper collar. Sizes S to XXL -- tell us your size in chat and we'll "
        "confirm the fit before it leaves the shop.",
    ),
    (
        "PRD_DMO_0002",
        "USR_DMO_S001",
        "Hand-Dyed Adire Fabric (2 Yards)",
        15000,
        None,
        18,
        "fashion",
        "adire-kimono",
        "Tie-dyed adire from Abeokuta in indigo, lime and plum. Two yards -- "
        "enough for a kimono, a skirt or a statement top.",
    ),
    (
        "PRD_DMO_0003",
        "USR_DMO_S001",
        "Aso-Oke Gele & Ipele Set (Blush)",
        12500,
        None,
        30,
        "fashion",
        "aso-oke-gele",
        "Hand-woven blush aso-oke for gele and ipele. Owambe-ready in minutes.",
    ),
    (
        "PRD_DMO_0004",
        "USR_DMO_S002",
        "iPhone 13 Pro, 128GB (UK-used)",
        620000,
        680000,
        6,
        "electronics",
        "iphone-13",
        "Battery health 89%, Face ID works, no scratches on the screen. Tested "
        "in front of you or delivered to your hostel with a 3-month warranty.",
    ),
    (
        "PRD_DMO_0005",
        "USR_DMO_S002",
        "Wireless Earbuds with Charging Case",
        18500,
        None,
        40,
        "electronics",
        "oraimo-freepods",
        "Pocket-size case, 30 hours of playback, clear calls. Brand new, "
        "sealed, with receipt.",
    ),
    (
        "PRD_DMO_0006",
        "USR_DMO_S002",
        "20,000mAh Power Bank (Fast Charge)",
        24500,
        28000,
        25,
        "electronics",
        "anker-powerbank",
        "Two full phone charges for when NEPA takes light. Fast charging over "
        "USB-C.",
    ),
    (
        "PRD_DMO_0007",
        "USR_DMO_S002",
        "JBL Flip Bluetooth Speaker",
        98000,
        None,
        8,
        "electronics",
        "jbl-flip-6",
        "Waterproof, loud, 12 hours of play. Original, not refurbished.",
    ),
    (
        "PRD_DMO_0008",
        "USR_DMO_S003",
        "Ofada Rice, 5kg",
        13500,
        None,
        60,
        "food-beverages",
        "ofada-rice",
        "Stone-free Ofada rice from Abeokuta, washed and bagged this week.",
    ),
    (
        "PRD_DMO_0009",
        "USR_DMO_S003",
        "Red Palm Oil, 4 Litres",
        9800,
        None,
        45,
        "food-beverages",
        "palm-oil",
        "Thick, fresh palm oil from Ijebu. No added colour, ever.",
    ),
    (
        "PRD_DMO_0010",
        "USR_DMO_S003",
        "Peeled Egusi Seeds, 1kg",
        6500,
        None,
        50,
        "food-beverages",
        "egusi",
        "Clean, peeled egusi. Grind it fresh for the pot -- or ask and we'll "
        "grind it for you.",
    ),
    (
        "PRD_DMO_0011",
        "USR_DMO_S003",
        "Abuja Yam (3 Tubers)",
        10500,
        None,
        35,
        "food-beverages",
        "abuja-yam",
        "Big, dry tubers that pound well. Delivered straight to your door.",
    ),
    (
        "PRD_DMO_0012",
        "USR_DMO_S004",
        "Nike Air Force 1 '07 (Thrift, Size 43)",
        45000,
        None,
        3,
        "fashion",
        "air-force-1",
        "Clean pair, deep-cleaned and deodorised. 9/10 condition.",
    ),
    (
        "PRD_DMO_0013",
        "USR_DMO_S004",
        "Vintage Levi's Denim Jacket",
        18000,
        None,
        5,
        "fashion",
        "denim-jacket",
        "90s wash, size M. The kind of jacket you keep for ten years.",
    ),
    (
        "PRD_DMO_0014",
        "USR_DMO_S004",
        "Vintage Raglan Graphic Tee",
        6500,
        None,
        20,
        "fashion",
        "graphic-tees",
        "Soft, washed raglan tee from the new bale. One of one.",
    ),
    (
        "PRD_DMO_0015",
        "USR_DMO_S005",
        "Raw Shea Butter, 500g",
        6500,
        None,
        70,
        "health-beauty",
        "shea-butter",
        "Unrefined shea from Saki. Skin, hair, everything.",
    ),
    (
        "PRD_DMO_0016",
        "USR_DMO_S005",
        "Ose Dudu (Raw African Black Soap), 500g",
        4000,
        None,
        80,
        "health-beauty",
        "black-soap",
        "Soft, raw black soap made with plantain-skin ash and palm kernel oil.",
    ),
    (
        "PRD_DMO_0017",
        "USR_DMO_S005",
        "Rosemary & Coconut Hair Oil, 100ml",
        7800,
        9000,
        40,
        "health-beauty",
        "hair-oil",
        "For length retention. Two drops on the scalp, three times a week.",
    ),
]

# (id, author, caption, image key or None, tagged product, minutes ago,
#  likers, comments[(author, text)])
POSTS = [
    (
        "PST_DMO_0001",
        "USR_DMO_S001",
        "New Ankara drop just landed 🔥 Twelve prints, all sizes. Come and see "
        "us at Bodija or order here -- we deliver around Ibadan today.",
        "post-ankara-drop",
        "PRD_DMO_0001",
        95,
        ["USR_DMO_B001", "USR_DMO_B002", "USR_DMO_B004"],
        [
            ("USR_DMO_B002", "That yellow one is calling my name 😍"),
            ("USR_DMO_S001", "@ifeoluwa.o it's yours sis, check DM!"),
        ],
    ),
    (
        "PST_DMO_0002",
        "USR_DMO_S003",
        "Fresh Ofada rice from Abeokuta this morning. Stone-free, I washed it "
        "myself. Who's cooking ofada stew this weekend?",
        "post-ofada",
        "PRD_DMO_0008",
        160,
        ["USR_DMO_B001", "USR_DMO_B003"],
        [("USR_DMO_B003", "Mama Bisi never disappoints 🙌")],
    ),
    (
        "PST_DMO_0003",
        "USR_DMO_S002",
        "Exam season = power bank season. 20,000mAh power banks back in stock, "
        "delivered to any hall on campus.",
        "post-powerbank",
        "PRD_DMO_0006",
        240,
        ["USR_DMO_B003", "USR_DMO_B004"],
        [
            ("USR_DMO_B001", "Do you deliver to Queens Hall?"),
            ("USR_DMO_S002", "Yes! Same day 👍"),
        ],
    ),
    (
        "PST_DMO_0004",
        "USR_DMO_S004",
        "Saturday bale is OPEN. AF1s, Levi's, and some tees you'll fight over. "
        "Agbowo, 10am.",
        "post-thrift",
        "PRD_DMO_0012",
        420,
        ["USR_DMO_B002", "USR_DMO_B003"],
        [],
    ),
    (
        "PST_DMO_0005",
        "USR_DMO_S005",
        "Small batch of raw shea just finished setting. No perfume, no fillers, "
        "just shea.",
        "post-shea",
        "PRD_DMO_0015",
        610,
        ["USR_DMO_B004"],
        [("USR_DMO_B004", "Ordering two tubs for my mum")],
    ),
    (
        "PST_DMO_0006",
        "USR_DMO_B004",
        "Wore my adire to class today and three people asked where I got it. "
        "@adasankara you're welcome",
        "adire-kimono",
        "PRD_DMO_0002",
        300,
        ["USR_DMO_B001", "USR_DMO_B002", "USR_DMO_S001"],
        [("USR_DMO_S001", "Ahh thank you! Come and pick the indigo one next")],
    ),
]

# Inbox threads for the demo buyer, oldest message first. The video's chat
# beat opens Ada's thread from the product page (Message Seller finds this
# room rather than starting a new one) and Temi sends one last line on camera.
# (seller, product, [(sender, type, text, minutes ago)])
CHATS = [
    (
        "USR_DMO_S001",
        "PRD_DMO_0001",
        [
            ("buyer", "product", "Hi, is this still available?", 14),
            ("seller", "text", "Yes o! S to XXL in stock. What size do you wear?", 13),
            ("buyer", "text", "Size L please. Can you deliver to UI today?", 11),
            (
                "seller",
                "text",
                "Definitely \U0001F64C Order now and our rider brings it to your hall this evening.",
                10,
            ),
        ],
    ),
    (
        "USR_DMO_S002",
        "PRD_DMO_0006",
        [
            ("buyer", "product", "Hi, is this still available?", 200),
            (
                "seller",
                "text",
                "Yes, brand new in the box. Want me to bring it to your hall?",
                190,
            ),
        ],
    ),
    (
        "USR_DMO_S003",
        "PRD_DMO_0008",
        [
            (
                "seller",
                "text",
                "Your Ofada is packed and ready. Thank you for buying from Mama Bisi! 💛",
                1440,
            ),
        ],
    ),
]

# Who the demo buyer follows (so their feed is personalised, not empty).
FOLLOWS = [
    (DEMO_BUYER_ID, "USR_DMO_S001"),
    (DEMO_BUYER_ID, "USR_DMO_S002"),
    (DEMO_BUYER_ID, "USR_DMO_S003"),
    ("USR_DMO_B002", "USR_DMO_S001"),
    ("USR_DMO_B003", "USR_DMO_S002"),
    ("USR_DMO_B004", "USR_DMO_S005"),
]

DEMO_WALLET_BALANCE = 150000


# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------

placeholders = []


def _find_image(subdir, key):
    # Avatars live in their own folder; product and post images may sit in a
    # subfolder or straight in demo/images/ (where the README says to put them).
    bases = [os.path.join(IMAGES_DIR, subdir)] if subdir else []
    if subdir != "avatars":
        bases.append(IMAGES_DIR)
    for base in bases:
        for ext in IMAGE_EXTS:
            path = os.path.join(base, key + ext)
            if os.path.isfile(path):
                return path
    return None


def _font(size):
    from PIL import ImageFont

    return ImageFont.load_default(size=size)


def _placeholder_tile(key, label, size=(1080, 1080)):
    """A tile nobody could mistake for a product photo: hatched, labelled."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", size, (236, 236, 236))
    draw = ImageDraw.Draw(img)
    w, h = size
    for x in range(-h, w, 48):
        draw.line([(x, 0), (x + h, h)], fill=(222, 222, 222), width=14)
    draw.rectangle([0, 0, w - 1, h - 1], outline=BRAND, width=12)
    draw.text(
        (w / 2, h / 2 - 70), "PLACEHOLDER", fill=BRAND, font=_font(84), anchor="mm"
    )
    # The bitmap font has no emoji; drop anything it would draw as a box.
    label = "".join(ch for ch in label if ord(ch) < 0x2000).strip()
    draw.text(
        (w / 2, h / 2 + 30), label[:38], fill=(60, 60, 60), font=_font(44), anchor="mm"
    )
    draw.text(
        (w / 2, h / 2 + 100),
        f"drop demo/images/{key}.jpg",
        fill=(120, 120, 120),
        font=_font(32),
        anchor="mm",
    )
    return img


def _initials_disc(name, size=400):
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (size, size), (253, 242, 239))
    draw = ImageDraw.Draw(img)
    draw.ellipse([0, 0, size - 1, size - 1], fill=BRAND)
    initials = "".join(p[0] for p in name.split()[:2]).upper()
    draw.text(
        (size / 2, size / 2), initials, fill="white", font=_font(150), anchor="mm"
    )
    return img


def stage_image(subdir, key, label, *, avatar=False):
    """Copy a provided image into the served media dir (or write a stand-in).

    Returns (storage_key, width, height, mime, is_placeholder).
    """
    from PIL import Image

    out_dir = os.path.join(MEDIA_DIR, "seed", subdir or "products")
    os.makedirs(out_dir, exist_ok=True)
    src = _find_image(subdir, key)
    if src:
        ext = os.path.splitext(src)[1].lower()
        dest = os.path.join(out_dir, key + ext)
        shutil.copyfile(src, dest)
        with Image.open(dest) as im:
            w, h = im.size
        mime = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
        }[ext]
        is_placeholder = False
    else:
        img = _initials_disc(label) if avatar else _placeholder_tile(key, label)
        dest = os.path.join(out_dir, key + ".png")
        img.save(dest)
        w, h = img.size
        mime = "image/png"
        is_placeholder = True
        if not avatar:
            placeholders.append(key)
    # Drop stale copies with another extension (e.g. placeholder .png left
    # behind once a real .jpg is provided).
    for ext in IMAGE_EXTS + (".png",):
        other = os.path.join(out_dir, key + ext)
        if other != dest and os.path.exists(other):
            os.remove(other)
    rel = os.path.relpath(dest, MEDIA_DIR)
    return rel, w, h, mime, is_placeholder


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------


def _media_url(storage_key):
    from main.config import settings

    return f"{settings.MEDIA_BASE_URL}/{storage_key}"


def upsert(session, model, pk, **fields):
    obj = session.get(model, pk)
    if obj is None:
        obj = model(**(pk if isinstance(pk, dict) else {"id": pk}))
        session.add(obj)
    for k, v in fields.items():
        setattr(obj, k, v)
    return obj


def reset_dependents(session, user_ids, product_ids, post_ids):
    """Delete everything a take can change, so the seed puts it back."""
    from seed_demo_stories import reset_stories

    from app.cart.models import Cart, CartItem
    from app.categories.models import PostCategory, ProductCategory, SellerCategory
    from app.chats.models import ChatDiscount, ChatMessage, ChatOffer, ChatRoom
    from app.media.models import Media, ProductImage, SocialMediaPost
    from app.socials.models import Follow, PostComment, PostLike, PostProduct
    from app.users.models import Buyer, Seller
    from sqlalchemy import or_, text

    # Niches point at seed media that is deleted below.
    reset_stories(session)

    rooms = session.query(ChatRoom.id).filter(
        ChatRoom.buyer_id.in_(user_ids), ChatRoom.seller_id.in_(user_ids)
    )
    room_ids = [r.id for r in rooms]
    if room_ids:
        msg_ids = [
            m.id
            for m in session.query(ChatMessage.id).filter(
                ChatMessage.room_id.in_(room_ids)
            )
        ]
        session.query(ChatDiscount).filter(ChatDiscount.room_id.in_(room_ids)).delete(
            synchronize_session=False
        )
        if msg_ids:
            session.query(ChatOffer).filter(ChatOffer.message_id.in_(msg_ids)).delete(
                synchronize_session=False
            )
            session.execute(
                text("DELETE FROM chat_message_reactions WHERE message_id = ANY(:ids)"),
                {"ids": msg_ids},
            )
        session.query(ChatMessage).filter(ChatMessage.room_id.in_(room_ids)).delete(
            synchronize_session=False
        )
        session.query(ChatRoom).filter(ChatRoom.id.in_(room_ids)).delete(
            synchronize_session=False
        )

    session.query(PostLike).filter(
        or_(PostLike.post_id.in_(post_ids), PostLike.user_id.in_(user_ids))
    ).delete(synchronize_session=False)
    session.execute(
        text(
            "DELETE FROM post_comment_reactions WHERE comment_id IN "
            "(SELECT id FROM post_comments WHERE post_id = ANY(:p))"
        ),
        {"p": post_ids},
    )
    session.query(PostComment).filter(PostComment.post_id.in_(post_ids)).delete(
        synchronize_session=False
    )
    session.query(PostProduct).filter(PostProduct.post_id.in_(post_ids)).delete(
        synchronize_session=False
    )
    session.query(PostCategory).filter(PostCategory.post_id.in_(post_ids)).delete(
        synchronize_session=False
    )
    session.query(SocialMediaPost).filter(SocialMediaPost.post_id.in_(post_ids)).delete(
        synchronize_session=False
    )
    session.query(Follow).filter(
        or_(Follow.follower_id.in_(user_ids), Follow.followee_id.in_(user_ids))
    ).delete(synchronize_session=False)
    session.query(ProductImage).filter(ProductImage.product_id.in_(product_ids)).delete(
        synchronize_session=False
    )
    session.query(ProductCategory).filter(
        ProductCategory.product_id.in_(product_ids)
    ).delete(synchronize_session=False)
    session.query(SellerCategory).filter(
        SellerCategory.seller_id.in_(
            session.query(Seller.id).filter(Seller.user_id.in_(user_ids))
        )
    ).delete(synchronize_session=False)
    # Seed media only: anything a take uploaded stays (it is not ours to drop).
    session.query(Media).filter(
        Media.user_id.in_(user_ids), Media.storage_key.like("seed/%")
    ).delete(synchronize_session=False)

    cart_ids = [
        c.id
        for c in session.query(Cart.id)
        .join(Buyer, Buyer.id == Cart.buyer_id)
        .filter(Buyer.user_id.in_(user_ids))
    ]
    if cart_ids:
        session.query(CartItem).filter(CartItem.cart_id.in_(cart_ids)).delete(
            synchronize_session=False
        )
    session.flush()


def seed():
    from app.categories.models import (
        Category,
        PostCategory,
        ProductCategory,
        SellerCategory,
    )
    from app.chats.models import ChatMessage, ChatRoom
    from app.markets.models import Market
    from app.media.models import Media, MediaType, ProductImage, SocialMediaPost
    from app.products.models import Product, ProductStatus
    from app.socials.models import (
        Follow,
        FollowType,
        Post,
        PostComment,
        PostLike,
        PostProduct,
        PostStatus,
    )
    from app.location.models import BrowseLocation
    from app.users.addresses import SavedAddress
    from app.users.models import (
        Buyer,
        Seller,
        SellerVerificationStatus,
        User,
        UserAddress,
    )
    from external.database import db

    session = db.session
    now = datetime.utcnow()
    ago = lambda minutes: now - timedelta(minutes=minutes)  # noqa: E731

    user_ids = [s["id"] for s in SELLERS] + [b["id"] for b in BUYERS]
    product_ids = [p[0] for p in PRODUCTS]
    post_ids = [p[0] for p in POSTS]

    reset_dependents(session, user_ids, product_ids, post_ids)

    categories = {
        c.slug: c for c in session.query(Category).filter(Category.parent_id.is_(None))
    }
    missing = {s["category"] for s in SELLERS} - set(categories)
    if missing:
        raise SystemExit(
            f"Categories missing ({missing}); run `flask populate-categories`."
        )
    markets = {m.slug: m for m in session.query(Market)}

    def add_media(owner_id, subdir, key, label, *, avatar=False):
        storage_key, w, h, mime, _ = stage_image(subdir, key, label, avatar=avatar)
        media = Media(
            storage_key=storage_key,
            media_type=MediaType.IMAGE,
            mime_type=mime,
            width=w,
            height=h,
            user_id=owner_id,
            alt_text=label,
            processing_status="completed",
            original_filename=os.path.basename(storage_key),
        )
        session.add(media)
        session.flush()
        return media

    def avatar_url(username, name):
        storage_key, *_ = stage_image("avatars", username, name, avatar=True)
        return _media_url(storage_key)

    # Users ---------------------------------------------------------------
    sellers_by_user = {}
    for i, s in enumerate(SELLERS):
        owner_name = s["email"].split("@")[0].replace(".", " ").title()
        user = upsert(
            session,
            User,
            s["id"],
            email=s["email"],
            username=s["username"],
            phone_number=s["phone"],
            is_seller=True,
            is_buyer=False,
            is_active=True,
            email_verified=True,
            deleted_at=None,
            profile_picture=avatar_url(s["username"], s["shop_name"]),
            created_at=ago(60 * 24 * (120 - i * 9)),
        )
        user.set_password(DEMO_PASSWORD)
        session.flush()
        seller = session.query(Seller).filter_by(user_id=user.id).one_or_none()
        if seller is None:
            seller = Seller(user_id=user.id)
            session.add(seller)
        market = markets.get(s["market"])
        seller.shop_name = s["shop_name"]
        seller.shop_slug = s["username"]
        seller.description = s["description"]
        seller.verification_status = SellerVerificationStatus.VERIFIED
        seller.is_active = True
        seller.market_id = market.id if market else None
        seller.shop_latitude, seller.shop_longitude = s["lat"], s["lng"]
        seller.shop_address = {
            "street_address": s["street"],
            "city": "Ibadan",
            "state": "Oyo",
            "country": "Nigeria",
        }
        seller.total_rating, seller.total_raters = s["rating"]
        seller.policies = {
            "returns": "Exchange within 3 days if it doesn't fit.",
            "shipping": "Same-day delivery within Ibadan.",
        }
        session.flush()
        session.add(
            SellerCategory(
                seller_id=seller.id,
                category_id=categories[s["category"]].id,
                is_primary=True,
            )
        )
        sellers_by_user[user.id] = seller

    for i, b in enumerate(BUYERS):
        user = upsert(
            session,
            User,
            b["id"],
            email=b["email"],
            username=b["username"],
            phone_number=b["phone"],
            is_buyer=True,
            is_seller=False,
            is_active=True,
            email_verified=True,
            deleted_at=None,
            profile_picture=avatar_url(b["username"], b["name"]),
            created_at=ago(60 * 24 * (60 - i * 5)),
        )
        user.set_password(DEMO_PASSWORD)
        session.flush()
        address = {
            "recipient_name": b["name"],
            "phone": b["phone"],
            "street_address": b["street"],
            "city": "Ibadan",
            "state": "Oyo",
            "country": "Nigeria",
            "latitude": b["lat"],
            "longitude": b["lng"],
        }
        buyer = session.query(Buyer).filter_by(user_id=user.id).one_or_none()
        if buyer is None:
            buyer = Buyer(user_id=user.id)
            session.add(buyer)
        buyer.buyername = b["name"]
        buyer.shipping_address = address
        buyer.is_active = True
        ua = session.query(UserAddress).filter_by(user_id=user.id).one_or_none()
        if ua is None:
            ua = UserAddress(user_id=user.id)
            session.add(ua)
        ua.street, ua.city, ua.state, ua.country = (
            b["street"],
            "Ibadan",
            "Oyo",
            "Nigeria",
        )
        ua.latitude, ua.longitude = b["lat"], b["lng"]
        # Checkout picks from the saved-address book (GET /users/addresses)
        # and stays disabled until one is chosen; the AppBar's location
        # switcher reads the browse location.
        session.query(SavedAddress).filter_by(user_id=user.id).delete()
        session.add(
            SavedAddress(
                user_id=user.id,
                label="Hostel" if "Hall" in b["street"] else "Home",
                formatted_address=f"{b['street']}, Ibadan, Oyo",
                latitude=b["lat"],
                longitude=b["lng"],
                city="Ibadan",
                state="Oyo",
                contact_name=b["name"],
                is_default=True,
            )
        )
        bl = session.query(BrowseLocation).filter_by(user_id=user.id).one_or_none()
        if bl is None:
            bl = BrowseLocation(user_id=user.id, latitude=b["lat"], longitude=b["lng"])
            session.add(bl)
        bl.latitude, bl.longitude = b["lat"], b["lng"]
        bl.label = b["area"]
        bl.state, bl.lga = "Oyo", "Ibadan North"
        bl.updated_at_utc = now
    session.flush()

    # Products ------------------------------------------------------------
    for i, (pid, uid, name, price, compare, stock, cat, img, desc) in enumerate(
        PRODUCTS
    ):
        seller = sellers_by_user[uid]
        product = upsert(
            session,
            Product,
            pid,
            name=name,
            description=desc,
            price=price,
            compare_at_price=compare,
            stock=stock,
            sku=f"DMO-{pid[-4:]}",
            seller_id=seller.id,
            status=ProductStatus.ACTIVE,
            # Newest first in the feed, in catalogue order.
            created_at=ago(30 + i * 37),
        )
        session.flush()
        media = add_media(uid, "", img, name)
        session.add(
            ProductImage(
                product_id=product.id,
                media_id=media.id,
                sort_order=0,
                is_featured=True,
                alt_text=name,
            )
        )
        session.add(
            ProductCategory(
                product_id=product.id, category_id=categories[cat].id, is_primary=True
            )
        )
    session.flush()

    # Posts ---------------------------------------------------------------
    for pid, uid, caption, img, tagged, minutes, likers, comments in POSTS:
        post = upsert(
            session,
            Post,
            pid,
            user_id=uid,
            caption=caption,
            status=PostStatus.ACTIVE,
            tags=[],
            created_at=ago(minutes),
        )
        session.flush()
        if img:
            media = add_media(uid, "posts", img, caption.split(".")[0])
            session.add(
                SocialMediaPost(
                    post_id=post.id,
                    media_id=media.id,
                    sort_order=0,
                    platform="markt",
                    post_type="post",
                    aspect_ratio="4:5",
                )
            )
        if tagged:
            session.add(PostProduct(post_id=post.id, product_id=tagged))
        # The tagged product's category (a buyer's post has no shop of its own).
        cat = next(p[6] for p in PRODUCTS if p[0] == tagged)
        session.add(
            PostCategory(
                post_id=post.id, category_id=categories[cat].id, is_primary=True
            )
        )
        for j, liker in enumerate(likers):
            session.add(
                PostLike(
                    user_id=liker, post_id=post.id, created_at=ago(minutes - 5 - j)
                )
            )
        for j, (author, text) in enumerate(comments):
            session.add(
                PostComment(
                    user_id=author,
                    post_id=post.id,
                    content=text,
                    created_at=ago(minutes - 10 - j * 4),
                )
            )
    session.flush()

    for follower, followee in FOLLOWS:
        session.add(
            Follow(
                follower_id=follower,
                followee_id=followee,
                follow_type=FollowType.CUSTOMER,
            )
        )

    # Chats ---------------------------------------------------------------
    products_by_id = {p[0]: p for p in PRODUCTS}
    for seller_uid, product_id, messages in CHATS:
        room = ChatRoom(
            buyer_id=DEMO_BUYER_ID,
            seller_id=seller_uid,
            product_id=product_id,
            unread_count_buyer=0,
            unread_count_seller=0,
            last_message_at=ago(messages[-1][3]),
        )
        session.add(room)
        session.flush()
        p = products_by_id[product_id]
        image = session.query(ProductImage).filter_by(product_id=product_id).first()
        for who, mtype, text, minutes in messages:
            sender = DEMO_BUYER_ID if who == "buyer" else seller_uid
            data = None
            if mtype == "product":
                data = {
                    "product_id": product_id,
                    "product": {
                        "id": product_id,
                        "name": p[2],
                        "price": p[3],
                        "image_url": image.media.get_url() if image else None,
                    },
                }
            is_read = True
            session.add(
                ChatMessage(
                    room_id=room.id,
                    sender_id=sender,
                    content=text,
                    message_type=mtype,
                    message_data=data,
                    is_read=is_read,
                    created_at=ago(minutes),
                )
            )

    # Feature-video state: shop branding, communities, Ada as a buyer too.
    from seed_demo_stories import seed_stories

    seed_stories(
        session,
        add_media=add_media,
        ago=ago,
        categories=categories,
        upsert=upsert,
        stage_image=stage_image,
    )
    session.commit()


def set_wallet_balance(user_id=DEMO_BUYER_ID, target=DEMO_WALLET_BALANCE):
    """Bring a demo wallet up to `target` (default: the demo buyer's)."""
    from decimal import Decimal

    from app.wallet.models import WalletReferenceType
    from app.wallet.services import WalletService

    current = Decimal(str(WalletService.get_balance(user_id)["available_balance"]))
    diff = Decimal(target) - current
    if diff > 0:
        stamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        WalletService.credit(
            user_id,
            diff,
            WalletReferenceType.ADJUSTMENT,
            f"demo-seed-{stamp}",
            description="Wallet top-up",
            idempotency_key=f"seed:demo-wallet:{user_id}:{stamp}",
        )
    elif diff < 0:
        print(
            f"  ! {user_id} wallet holds {current}, above the {target} target; left as is"
        )


SHOWCASE_PRODUCT = "PRD_DMO_0006"  # Anker power bank from Tobi Gadgets


def ensure_showcase_order(api_base):
    """One paid, shipped order so order tracking has something to show.

    Placed through the real HTTP API -- cart, checkout, wallet payment, the
    seller marking it shipped -- rather than inserted, so every row the
    tracking screen reads is one the app itself would have written. Skipped
    when the demo buyer already has one, so a re-seed leaves it alone.
    """
    import uuid

    import requests

    def login(email, role):
        r = requests.post(
            f"{api_base}/users/login",
            json={"email": email, "password": DEMO_PASSWORD, "account_type": role},
            timeout=30,
        )
        r.raise_for_status()
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    def items_of(resp):
        body = resp.json()
        return body if isinstance(body, list) else body.get("items", [])

    buyer = login(BUYERS[0]["email"], "buyer")
    orders = items_of(
        requests.get(
            f"{api_base}/orders/?page=1&per_page=50", headers=buyer, timeout=30
        )
    )
    order_id, total, placed = None, None, False
    for o in orders:
        if any(i.get("product_id") == SHOWCASE_PRODUCT for i in o.get("items", [])):
            if o.get("status") != "pending_payment":
                return o.get("id") or o.get("order_id"), False
            # A previous run stopped between checkout and payment: finish it.
            order_id, total = o.get("id") or o.get("order_id"), o["total"]

    if order_id is None:
        b = BUYERS[0]
        address = {
            "recipient_name": b["name"],
            "phone": b["phone"],
            "street_address": b["street"],
            "city": "Ibadan",
            "state": "Oyo",
            "country": "Nigeria",
            "latitude": b["lat"],
            "longitude": b["lng"],
        }
        requests.post(
            f"{api_base}/cart/add",
            headers=buyer,
            timeout=30,
            json={"product_id": SHOWCASE_PRODUCT, "quantity": 1},
        ).raise_for_status()
        seller_row = requests.get(
            f"{api_base}/products/{SHOWCASE_PRODUCT}", headers=buyer, timeout=30
        ).json()["seller"]
        seller_id = seller_row.get("id") or seller_row.get("seller_id")
        q = requests.post(
            f"{api_base}/delivery/quote",
            headers=buyer,
            timeout=30,
            json={
                "seller_id": seller_id,
                "dropoff_latitude": b["lat"],
                "dropoff_longitude": b["lng"],
                "item_count": 1,
            },
        )
        if not q.ok:
            raise SystemExit(
                f"delivery quote failed ({q.status_code}): {q.text[:300]} "
                "-- are the Ibadan zones active? (seed_delivery_areas --activate)"
            )
        r = requests.post(
            f"{api_base}/cart/checkout",
            headers=buyer,
            timeout=30,
            json={
                "shipping_address": address,
                "billing_address": address,
                "notes": "Please call when you get to the hall gate",
                "use_saved_address": False,
                "seller_id": seller_id,
                "delivery_quote_id": q.json()["id"],
                "idempotency_key": f"demo-showcase-{uuid.uuid4()}",
            },
        )
        r.raise_for_status()
        order_id, total, placed = r.json()["order_id"], r.json()["total"], True

    r = requests.post(
        f"{api_base}/payments/create",
        headers=buyer,
        timeout=30,
        json={
            "order_id": order_id,
            "currency": "NGN",
            "method": "wallet",
            "amount": total,
            "idempotency_key": f"demo-showcase-pay-{order_id}",
        },
    )
    if not r.ok:
        raise SystemExit(f"showcase payment failed ({r.status_code}): {r.text[:300]}")

    return order_id, placed


RIDER = {
    "phone": "2348000000101",
    "name": "Kunle Adebayo",
    "vehicle": "BIKE",
    "rating": 4.8,
}


def ensure_rider_en_route(api_base, order_id):
    """Put a rider on the showcase order and get them on the road.

    Through the rider API, as the rider app would: sign in (the code comes
    from dev_rider_login.py, which writes it where the login endpoint reads
    it), go online near the shop, accept, then arrive -> picked up -> en route.
    Re-running skips whatever has already happened.
    """
    import subprocess

    import requests

    subprocess.run(
        [
            sys.executable,
            os.path.join(ROOT, "scripts", "dev_rider_login.py"),
            RIDER["phone"],
            "--name",
            RIDER["name"],
        ],
        check=True,
        capture_output=True,
    )
    r = requests.post(
        f"{api_base}/deliveries/auth/login",
        timeout=30,
        json={"phone_number": RIDER["phone"], "otp": "123456"},
    )
    r.raise_for_status()
    rider = {"Authorization": f"Bearer {r.json()['access_token']}"}

    shop = next(s for s in SELLERS if s["id"] == "USR_DMO_S002")
    requests.post(
        f"{api_base}/deliveries/partners/me/location",
        headers=rider,
        timeout=30,
        json={"lat": shop["lat"], "lng": shop["lng"]},
    ).raise_for_status()

    active = requests.get(
        f"{api_base}/deliveries/assignments/active", headers=rider, timeout=30
    ).json()
    active = (
        active
        if isinstance(active, list)
        else active.get("assignments", active.get("items", []))
    )
    assignment = next((a for a in active if a.get("order_id") == order_id), None)
    if assignment is None:
        r = requests.post(
            f"{api_base}/deliveries/orders/{order_id}/accept", headers=rider, timeout=30
        )
        if not r.ok:  # already delivered, or taken in an earlier run
            print(
                f"  ! rider could not accept {order_id}: {r.status_code} {r.text[:120]}"
            )
            return
        assignment_id = r.json()["assignment_id"]
        current = None
    else:
        assignment_id = assignment.get("assignment_id") or assignment.get("id")
        current = assignment.get("logistical_status")

    steps = ["ARRIVED_PICKUP", "PICKED_UP", "EN_ROUTE_TO_DROPOFF"]
    done = steps.index(current) + 1 if current in steps else 0
    for step in steps[done:]:
        requests.patch(
            f"{api_base}/deliveries/assignments/{assignment_id}/status",
            headers=rider,
            timeout=30,
            json={"status": step},
        ).raise_for_status()

    from sqlalchemy import text

    from external.database import db

    db.session.execute(
        text(
            "UPDATE delivery_users SET vehicle_type = :v, rating = :r WHERE phone_number = :p"
        ),
        {"v": RIDER["vehicle"], "r": RIDER["rating"], "p": RIDER["phone"]},
    )
    db.session.commit()


def reset_caches():
    from external.redis import redis_client

    r = redis_client.client
    patterns = [
        "feed:*",
        "user:USR_DMO_*",
        "user:current_role:USR_DMO_*",
        "post:PST_DMO_*",
        "product:PRD_DMO_*",
        "delivery:serviceable:*",
        "niche:*",
        "user:*niches*",
    ]
    dropped = 0
    for pattern in patterns:
        keys = list(r.scan_iter(pattern, count=500))
        if keys:
            dropped += r.delete(*keys)
    # Live like counts are read from this zset, not the table.
    for pid, *_rest in POSTS:
        likers = _rest[5]
        if likers:
            r.zadd(f"post:{pid}:likes", {u: 1 for u in likers})
    try:
        from app.products.services import ProductService
        from app.socials.tasks import update_popular_content

        ProductService.update_trending_products()
        update_popular_content.run()
    except Exception as e:  # trending is a nicety, not a requirement
        print(f"  ! trending rebuild skipped: {e}")
    return dropped


def warm_feed(api_base):
    """Cache the demo buyer's feed in its stable order.

    A cache-miss build and a force_refresh build rank the same items
    differently, so a take that starts on a cold cache can see the feed
    reshuffle under the camera when the app later refreshes. One forced
    build here leaves the 30-minute cache holding the order every request
    will see -- re-seed before a take, not just once a day.
    """
    import requests

    r = requests.post(
        f"{api_base}/users/login",
        timeout=30,
        json={
            "email": BUYERS[0]["email"],
            "password": DEMO_PASSWORD,
            "account_type": "buyer",
        },
    )
    r.raise_for_status()
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    requests.get(
        f"{api_base}/socials/feed?page=1&per_page=20&force_refresh=true",
        headers=headers,
        timeout=60,
    ).raise_for_status()


def mark_achievements_seen():
    """A badge earned by the showcase order would otherwise pop a celebration
    over the first shot after login."""
    from sqlalchemy import text

    from external.database import db

    db.session.execute(
        text(
            "UPDATE gam_user_badges SET seen_at = now() WHERE seen_at IS NULL "
            "AND user_id LIKE 'USR_DMO_%'"
        )
    )
    # Same for the bell: orders and chats from earlier takes pile up unread
    # notifications, and the badge count would change from one beat to the next.
    db.session.execute(
        text(
            "UPDATE notifications SET is_read = true WHERE is_read = false "
            "AND user_id LIKE 'USR_DMO_%'"
        )
    )
    db.session.commit()


def clear_demo_cart():
    from app.cart.models import Cart, CartItem
    from app.users.models import Buyer
    from external.database import db

    cart_ids = [
        c.id
        for c in db.session.query(Cart.id)
        .join(Buyer, Buyer.id == Cart.buyer_id)
        .filter(Buyer.user_id == DEMO_BUYER_ID)
    ]
    if cart_ids:
        db.session.query(CartItem).filter(CartItem.cart_id.in_(cart_ids)).delete(
            synchronize_session=False
        )
        db.session.commit()


def main() -> int:
    import argparse

    from main.config import settings

    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--api",
        default="http://localhost:8000/api/v1",
        help="API the showcase order is placed through.",
    )
    parser.add_argument(
        "--no-showcase",
        action="store_true",
        help="Skip placing the shipped showcase order.",
    )
    parser.add_argument(
        "--no-stories",
        action="store_true",
        help="Skip the feature-video orders and offers (seed_demo_stories).",
    )
    args = parser.parse_args()

    if os.environ.get("MARKT_DEMO") != "1" or settings.ENV == "production":
        print(
            "Refusing: set MARKT_DEMO=1 (and not ENV=production). This deletes "
            "and recreates demo-owned rows."
        )
        return 2
    if not settings.MEDIA_BASE_URL:
        print("Refusing: MEDIA_BASE_URL is empty, so seeded images would point at S3.")
        return 2

    from main.setup import create_flask_app

    app = create_flask_app()
    with app.app_context():
        seed()
        # Funded before the showcase order pays from it, and again after.
        set_wallet_balance()
        showcase = None
        if not args.no_showcase:
            showcase = ensure_showcase_order(args.api)
            ensure_rider_en_route(args.api, showcase[0])
            # The order went through the buyer's cart and wallet; put both back.
            clear_demo_cart()
        stories = []
        if not args.no_stories:
            import seed_demo_stories as st

            for uid in st.story_wallets():
                set_wallet_balance(uid, st.STORY_WALLET)
            stories.append(
                ("pending order for Ada", st.ensure_pending_allocation(args.api))
            )
            stories.append(("discount offer", st.ensure_discount_offer(args.api)))
            stories.append(
                ("shared-delivery neighbours", st.ensure_batch_neighbours(args.api))
            )
        set_wallet_balance()
        mark_achievements_seen()
        dropped = reset_caches()
    # After the app context closes: the API (not this process) builds the feed.
    warm_feed(args.api)
    for label, result in stories:
        print(f"Story: {label}: {result}")
    if showcase:
        print(
            f"Showcase order {showcase[0]} ({'placed' if showcase[1] else 'already there'})."
        )

    print(
        f"Seeded {len(SELLERS)} shops, {len(BUYERS)} buyers, {len(PRODUCTS)} products, "
        f"{len(POSTS)} posts, {len(CHATS)} chat threads; cleared {dropped} cache keys."
    )
    print(f"Demo login: {BUYERS[0]['email']} / {DEMO_PASSWORD}  (buyer)")
    if placeholders:
        print(
            f"\n⚠ {len(placeholders)} images are PLACEHOLDERS -- drop real ones into "
            f"demo/images/ and re-run:\n  " + ", ".join(sorted(set(placeholders)))
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
