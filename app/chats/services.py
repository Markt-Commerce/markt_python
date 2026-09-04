import logging
from datetime import datetime
from typing import Any, Dict, Optional, List, Tuple

# package imports
from sqlalchemy.orm import joinedload
from sqlalchemy.exc import SQLAlchemyError

# project imports
from external.database import db
from external.redis import redis_client
from app.libs.session import session_scope, read_scope
from app.libs.errors import (
    NotFoundError,
    ValidationError,
    ForbiddenError,
    APIError,
)

from app.users.models import User, Seller
from app.products.models import Product
from app.requests.models import BuyerRequest

# app imports
from app.libs.models import ReactionType
from .models import (
    ChatRoom,
    ChatMessage,
    ChatOffer,
    ChatMessageReaction,
    ChatDiscount,
    DiscountType,
    DiscountStatus,
)

logger = logging.getLogger(__name__)


class ChatService:
    """Service for managing chat functionality"""

    # Cache keys
    CACHE_KEYS = {
        "user_rooms": "chat:user:{user_id}:rooms",
        "room_messages": "chat:room:{room_id}:messages",
        "typing": "chat:typing:{room_id}:{user_id}",
        "online_status": "chat:online:{user_id}",
        "unread_count": "chat:unread:{user_id}:{room_id}",
    }

    @staticmethod
    def _build_product_snapshot(product_id: str, session) -> Optional[Dict[str, Any]]:
        """Build a product snapshot for chat message display (name, price, image_url).

        Returns None if product not found or unavailable. Used to enrich product/offer
        messages so the frontend can render product cards without an extra API call.
        """
        if not product_id:
            return None
        product = (
            session.query(Product)
            .options(joinedload(Product.images))
            .filter(Product.id == product_id)
            .first()
        )
        if not product:
            return None
        image_url = None
        if product.images and len(product.images) > 0:
            first_image = product.images[0]
            if first_image.media:
                try:
                    image_url = first_image.media.get_url()
                except Exception:
                    pass
        return {
            "id": product.id,
            "name": product.name,
            "price": float(product.price),
            "currency": "NGN",
            "image_url": image_url,
        }

    @staticmethod
    def _format_room_messages(messages_iter, session) -> List[Dict[str, Any]]:
        """Format messages for room_data (socket join), with enriched product/offer."""
        # Materialise first: the caller may pass a generator (reversed(...)),
        # and the offers below need the ids up front.
        msgs = list(messages_iter)
        # One query for every offer on the page instead of one per offer
        # message -- the same batching get_room_messages already got in #92.
        offers_by_message = ChatService._batch_offers(session, [m.id for m in msgs])

        # And one query for every product referenced by the page, rather than a
        # SELECT per product/offer message.
        wanted = [o.product_id for o in offers_by_message.values()]
        for m in msgs:
            if m.message_type == "product" and isinstance(m.message_data, dict):
                wanted.append(m.message_data.get("product_id"))
        snapshots = ChatService._batch_product_snapshots(session, wanted)

        formatted = []
        for msg in msgs:
            msg_dict = {
                "id": msg.id,
                "content": msg.content,
                "message_type": msg.message_type,
                "message_data": ChatService._enrich_message_data(
                    msg.message_type, msg.message_data, msg.id, session, snapshots
                ),
                "sender_id": msg.sender_id,
                "sender_username": msg.sender.username,
                "is_read": msg.is_read,
                "created_at": msg.created_at.isoformat(),
            }
            if msg.message_type == "offer":
                offer = offers_by_message.get(msg.id)
                if offer:
                    offer_payload = {
                        "id": offer.id,
                        "product_id": offer.product_id,
                        "price": float(offer.price),
                        "status": offer.status,
                    }
                    product_snapshot = snapshots.get(offer.product_id)
                    if product_snapshot:
                        offer_payload["product"] = product_snapshot
                    msg_dict["offer"] = offer_payload
            formatted.append(msg_dict)
        return formatted

    @staticmethod
    def _enrich_message_data(
        message_type: str,
        message_data: Optional[Dict[str, Any]],
        message_id: int,
        session,
        snapshots: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Enrich message_data with product snapshot for product messages.

        For backward compatibility, old messages may have only product_id.
        This adds a product snapshot (name, price, image_url) when missing.
        """
        if message_data is None:
            return None
        result = dict(message_data)
        if message_type == "product":
            pid = result.get("product_id")
            if pid and "product" not in result:
                # Prefer the batch the caller already built; fall back to a
                # single fetch for one-off callers.
                snapshot = (
                    snapshots.get(pid)
                    if snapshots is not None
                    else ChatService._build_product_snapshot(pid, session)
                )
                if snapshot:
                    result["product"] = snapshot
        return result

    @staticmethod
    def _user_pair_room_filter(buyer_id: str, seller_id: str):
        """Match a chat room regardless of which user is stored as buyer or seller."""
        return db.or_(
            db.and_(
                ChatRoom.buyer_id == buyer_id,
                ChatRoom.seller_id == seller_id,
            ),
            db.and_(
                ChatRoom.buyer_id == seller_id,
                ChatRoom.seller_id == buyer_id,
            ),
        )

    @staticmethod
    def _find_room_for_user_pair(session, buyer_id: str, seller_id: str):
        """Return the most recently active room between two users, if any."""
        return (
            session.query(ChatRoom)
            .filter(ChatService._user_pair_room_filter(buyer_id, seller_id))
            .order_by(
                ChatRoom.last_message_at.desc().nullslast(),
                ChatRoom.id.desc(),
            )
            .first()
        )

    @staticmethod
    def _apply_room_context(
        room: ChatRoom,
        product_id: Optional[str],
        request_id: Optional[str],
    ) -> None:
        """Attach product/request context to a room when not already set."""
        if product_id and room.product_id is None:
            room.product_id = product_id
        if request_id and room.request_id is None:
            room.request_id = request_id

    @staticmethod
    def create_or_get_chat_room(
        buyer_id: str,
        seller_id: str,
        product_id: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> ChatRoom:
        """Create or get the single chat room between a buyer and seller.

        One conversation exists per user pair. product_id and request_id are
        optional context (e.g. opened from a product page) and do not create
        separate rooms. Product-specific content belongs on messages.
        """
        try:
            if buyer_id == seller_id:
                raise ValidationError("Cannot create a chat room with yourself")

            with session_scope() as session:
                buyer = session.query(User).filter(User.id == buyer_id).first()
                if not buyer:
                    raise NotFoundError(f"Buyer with ID {buyer_id} not found")

                seller = session.query(User).filter(User.id == seller_id).first()
                if not seller:
                    raise NotFoundError(f"Seller with ID {seller_id} not found")

                if product_id:
                    product = (
                        session.query(Product).filter(Product.id == product_id).first()
                    )
                    if not product:
                        raise NotFoundError(f"Product with ID {product_id} not found")

                if request_id:
                    request_obj = (
                        session.query(BuyerRequest)
                        .filter(BuyerRequest.id == request_id)
                        .first()
                    )
                    if not request_obj:
                        raise NotFoundError(f"Request with ID {request_id} not found")

                existing_room = ChatService._find_room_for_user_pair(
                    session, buyer_id, seller_id
                )
                if existing_room:
                    ChatService._apply_room_context(
                        existing_room, product_id, request_id
                    )
                    return existing_room

                room = ChatRoom(
                    buyer_id=buyer_id,
                    seller_id=seller_id,
                    product_id=product_id,
                    request_id=request_id,
                )

                session.add(room)
                session.flush()

                ChatService._cache_user_room(buyer_id, room)
                ChatService._cache_user_room(seller_id, room)

                return room

        except APIError:
            raise
        except Exception as e:
            logger.exception("Failed to create chat room: %s", e)
            raise APIError("Failed to create chat room", status_code=500)

    @staticmethod
    def get_user_chat_rooms(
        user_id: str, page: int = 1, per_page: int = 20
    ) -> Dict[str, Any]:
        """Get chat rooms for a user with recent messages"""
        try:
            # read_scope, not session_scope: session_scope commits on exit, and a
            # commit expires every loaded instance. Anything touched afterwards
            # then re-SELECTs itself one row at a time.
            with read_scope() as session:
                membership = db.or_(
                    ChatRoom.buyer_id == user_id,
                    ChatRoom.seller_id == user_id,
                )

                # joinedload(ChatRoom.messages) used to be here. It pulled the
                # entire message history of every room on the page into memory
                # just to render a one-line preview -- the cost grew with how
                # much people had talked, which is the wrong thing to scale on.
                rooms = (
                    session.query(ChatRoom)
                    .options(
                        joinedload(ChatRoom.buyer),
                        joinedload(ChatRoom.seller),
                        joinedload(ChatRoom.product).joinedload(Product.images),
                        joinedload(ChatRoom.request),
                    )
                    .filter(membership)
                    # id.desc() is a tiebreaker, not decoration: last_message_at
                    # is null for a room nobody has spoken in yet, and ties on
                    # equal timestamps otherwise. Without a stable second key the
                    # order varies between calls, so paging can repeat or skip a
                    # room. _find_room_for_user_pair already orders this way.
                    .order_by(
                        ChatRoom.last_message_at.desc().nullslast(),
                        ChatRoom.id.desc(),
                    )
                    .offset((page - 1) * per_page)
                    .limit(per_page)
                    .all()
                )

                room_ids = [room.id for room in rooms]
                last_messages = ChatService._batch_last_messages(session, room_ids)
                unread_counts = ChatService._batch_unread_counts(
                    session, room_ids, user_id
                )

                # Real total, so the client can page. This used to report
                # len(enhanced_rooms) -- the size of the current page, which
                # meant the last page and a full page looked identical.
                total = session.query(ChatRoom).filter(membership).count()

                # Enhance rooms with additional data
                enhanced_rooms = []
                for room in rooms:
                    last_message = last_messages.get(room.id)
                    unread_count = unread_counts.get(room.id, 0)

                    # Get other user info
                    other_user = room.seller if room.buyer_id == user_id else room.buyer

                    room_data = {
                        "id": room.id,
                        "other_user": {
                            "id": other_user.id,
                            "username": other_user.username,
                            "profile_picture": other_user.profile_picture,
                            # hasattr() on a relationship is always True -- the
                            # attribute exists whether or not it resolves to a
                            # row -- so this reported every counterparty as a
                            # seller, buyers included.
                            "is_seller": other_user.seller_account is not None,
                        },
                        "product": (
                            {
                                "id": room.product.id,
                                "name": room.product.name,
                                "price": float(room.product.price),
                                "image": (
                                    room.product.images[0].media.get_url()
                                    if (
                                        room.product.images
                                        and len(room.product.images) > 0
                                        and room.product.images[0].media
                                    )
                                    else None
                                ),
                            }
                            if room.product
                            else None
                        ),
                        "request": (
                            {
                                "id": room.request.id,
                                "title": room.request.title,
                                "description": room.request.description,
                            }
                            if room.request
                            else None
                        ),
                        "last_message": (
                            {
                                "id": last_message.id,
                                "sender_id": last_message.sender_id,
                                "content": last_message.content,
                                "message_type": last_message.message_type,
                                "created_at": last_message.created_at,
                            }
                            if last_message
                            else None
                        ),
                        "unread_count": unread_count,
                        "last_message_at": (
                            room.last_message_at if room.last_message_at else None
                        ),
                    }

                    enhanced_rooms.append(room_data)

                return {
                    "rooms": enhanced_rooms,
                    "pagination": {
                        "page": page,
                        "per_page": per_page,
                        "total": total,
                    },
                }

        except Exception as e:
            logger.error(f"Failed to get chat rooms: {str(e)}")
            raise APIError("Failed to get chat rooms")

    @staticmethod
    def _batch_product_snapshots(session, product_ids) -> Dict[str, Dict[str, Any]]:
        """Snapshots for many products in one query.

        _build_product_snapshot() fetches a single product, so calling it while
        formatting a page of messages cost one SELECT per product/offer message.
        """
        ids = {pid for pid in product_ids if pid}
        if not ids:
            return {}
        products = (
            session.query(Product)
            .options(joinedload(Product.images))
            .filter(Product.id.in_(ids))
            .all()
        )
        snapshots: Dict[str, Dict[str, Any]] = {}
        for product in products:
            image_url = None
            if product.images and len(product.images) > 0:
                first_image = product.images[0]
                if first_image.media:
                    try:
                        image_url = first_image.media.get_url()
                    except Exception:
                        pass
            snapshots[product.id] = {
                "id": product.id,
                "name": product.name,
                "price": float(product.price),
                "currency": "NGN",
                "image_url": image_url,
            }
        return snapshots

    @staticmethod
    def _batch_offers(session, message_ids: List[int]) -> Dict[int, ChatOffer]:
        """Offers keyed by message id, in one query instead of one per offer."""
        if not message_ids:
            return {}
        rows = (
            session.query(ChatOffer).filter(ChatOffer.message_id.in_(message_ids)).all()
        )
        return {offer.message_id: offer for offer in rows}

    @staticmethod
    def _batch_last_messages(session, room_ids: List[int]) -> Dict[int, ChatMessage]:
        """Newest message per room, in one query instead of one query per room."""
        if not room_ids:
            return {}
        newest = (
            db.select(
                ChatMessage,
                db.func.row_number()
                .over(
                    partition_by=ChatMessage.room_id,
                    # id.desc() breaks ties: messages sent in the same instant
                    # share a created_at, and without it "the last message"
                    # varies between reads.
                    order_by=(
                        ChatMessage.created_at.desc(),
                        ChatMessage.id.desc(),
                    ),
                )
                .label("rn"),
            )
            .filter(ChatMessage.room_id.in_(room_ids))
            .subquery()
        )
        aliased = db.aliased(ChatMessage, newest)
        rows = session.query(aliased).filter(newest.c.rn == 1).all()
        return {msg.room_id: msg for msg in rows}

    @staticmethod
    def _batch_unread_counts(
        session, room_ids: List[int], user_id: str
    ) -> Dict[int, int]:
        """Unread count per room, in one grouped query.

        The old path called _get_unread_count() per room, and that helper opened
        its own session_scope -- so every room both cost a query and committed,
        expiring the rooms and users already loaded above.
        """
        if not room_ids:
            return {}
        rows = (
            session.query(ChatMessage.room_id, db.func.count(ChatMessage.id))
            .filter(
                ChatMessage.room_id.in_(room_ids),
                ChatMessage.sender_id != user_id,
                ChatMessage.is_read.is_(False),
            )
            .group_by(ChatMessage.room_id)
            .all()
        )
        return {room_id: count for room_id, count in rows}

    @staticmethod
    def get_room_messages(
        room_id: int, user_id: str, page: int = 1, per_page: int = 50
    ) -> Dict[str, Any]:
        """Get messages for a specific chat room"""
        try:
            # Access check and the read-receipt write happen first, in a scope
            # that is allowed to commit. Doing the write *during* the read was
            # the bug: the commit expired every message and sender already
            # loaded, so the formatting loop re-fetched them one row at a time.
            # Marking before reading also keeps the response identical to what
            # it was -- messages come back already flagged read.
            with session_scope() as session:
                room = (
                    session.query(ChatRoom)
                    .filter(
                        ChatRoom.id == room_id,
                        db.or_(
                            ChatRoom.buyer_id == user_id,
                            ChatRoom.seller_id == user_id,
                        ),
                    )
                    .first()
                )
                if not room:
                    raise ForbiddenError("Access denied to this chat room")

            ChatService._mark_messages_as_read(room_id, user_id)

            with read_scope() as session:
                # Get messages with pagination
                messages = (
                    session.query(ChatMessage)
                    .options(joinedload(ChatMessage.sender))
                    .filter(ChatMessage.room_id == room_id)
                    .order_by(
                        ChatMessage.created_at.desc(),
                        ChatMessage.id.desc(),
                    )
                    .offset((page - 1) * per_page)
                    .limit(per_page)
                    .all()
                )

                # Offers for this page, batched. Previously one SELECT per
                # message that happened to be an offer.
                offers_by_message = ChatService._batch_offers(
                    session, [m.id for m in messages]
                )

                total = (
                    session.query(ChatMessage)
                    .filter(ChatMessage.room_id == room_id)
                    .count()
                )

                # Format messages
                formatted_messages = []
                for message in reversed(messages):  # Reverse to get chronological order
                    message_data = {
                        "id": message.id,
                        "room_id": message.room_id,
                        "sender_id": message.sender_id,
                        "sender": {
                            "id": message.sender.id,
                            "username": message.sender.username,
                            "profile_picture": message.sender.profile_picture,
                            "is_seller": message.sender.is_seller,
                        },
                        "content": message.content,
                        "message_type": message.message_type,
                        "message_data": ChatService._enrich_message_data(
                            message.message_type,
                            message.message_data,
                            message.id,
                            session,
                        ),
                        "is_read": message.is_read,
                        "read_at": message.read_at if message.read_at else None,
                        "created_at": message.created_at,
                    }

                    # Add offer data if message contains an offer
                    if message.message_type == "offer":
                        offer = offers_by_message.get(message.id)
                        if offer:
                            offer_payload = {
                                "id": offer.id,
                                "product_id": offer.product_id,
                                "price": float(offer.price),
                                "status": offer.status,
                            }
                            # Add product snapshot for frontend product card
                            product_snapshot = ChatService._build_product_snapshot(
                                offer.product_id, session
                            )
                            if product_snapshot:
                                offer_payload["product"] = product_snapshot
                            message_data["offer"] = offer_payload

                    formatted_messages.append(message_data)

                return {
                    "messages": formatted_messages,
                    "pagination": {
                        "page": page,
                        "per_page": per_page,
                        "total": total,
                    },
                }

        except ForbiddenError:
            raise
        except Exception as e:
            logger.error(f"Failed to get room messages: {str(e)}")
            raise APIError("Failed to get messages")

    @staticmethod
    def user_has_access_to_room(user_id: str, room_id: int) -> bool:
        """Check if user has access to a specific chat room"""
        try:
            with session_scope() as session:
                room = (
                    session.query(ChatRoom)
                    .filter(
                        ChatRoom.id == room_id,
                        db.or_(
                            ChatRoom.buyer_id == user_id,
                            ChatRoom.seller_id == user_id,
                        ),
                    )
                    .first()
                )
                return room is not None
        except Exception as e:
            logger.error(f"Failed to check room access: {str(e)}")
            return False

    @staticmethod
    def get_room_with_messages(room_id: int, user_id: str) -> Dict[str, Any]:
        """Get room details with recent messages for socket connection.

        Runs on every chat open over the socket, so it had the same three
        problems its siblings did (see #92) and was simply missed.
        """
        try:
            # read_scope: session_scope commits on exit, and _get_unread_count
            # opened a second one mid-read -- a commit expires every loaded
            # instance, so anything touched afterwards re-SELECTs a row at a
            # time.
            with read_scope() as session:
                # Verify user has access to this room
                room = (
                    session.query(ChatRoom)
                    .options(
                        joinedload(ChatRoom.buyer),
                        joinedload(ChatRoom.seller),
                        joinedload(ChatRoom.product),
                        joinedload(ChatRoom.request),
                    )
                    .filter(
                        ChatRoom.id == room_id,
                        db.or_(
                            ChatRoom.buyer_id == user_id,
                            ChatRoom.seller_id == user_id,
                        ),
                    )
                    .first()
                )

                if not room:
                    raise ForbiddenError("Access denied to this chat room")

                # Get recent messages (last 50)
                messages = (
                    session.query(ChatMessage)
                    .options(joinedload(ChatMessage.sender))
                    .filter(ChatMessage.room_id == room_id)
                    .order_by(ChatMessage.created_at.desc())
                    .limit(50)
                    .all()
                )

                # Get other user info
                other_user = room.seller if room.buyer_id == user_id else room.buyer

                return {
                    "room_id": room.id,
                    "other_user": {
                        "id": other_user.id,
                        "username": other_user.username,
                        "profile_picture": other_user.profile_picture,
                        # hasattr() on a relationship is always True -- the
                        # attribute exists whether or not it resolves to a row --
                        # so every counterparty was reported as a seller.
                        "is_seller": other_user.seller_account is not None,
                    },
                    "product": (
                        {
                            "id": room.product.id,
                            "name": room.product.name,
                            "price": float(room.product.price),
                            "image": (
                                room.product.images[0].media.get_url()
                                if (
                                    room.product.images
                                    and len(room.product.images) > 0
                                    and room.product.images[0].media
                                )
                                else None
                            ),
                        }
                        if room.product
                        else None
                    ),
                    "request": (
                        {
                            "id": room.request.id,
                            "title": room.request.title,
                            "description": room.request.description,
                        }
                        if room.request
                        else None
                    ),
                    "messages": ChatService._format_room_messages(
                        reversed(messages), session
                    ),
                    # Counted in this session rather than through
                    # _get_unread_count(), which opens its own scope and commits.
                    "unread_count": (
                        session.query(db.func.count(ChatMessage.id))
                        .filter(
                            ChatMessage.room_id == room.id,
                            ChatMessage.sender_id != user_id,
                            ChatMessage.is_read.is_(False),
                        )
                        .scalar()
                        or 0
                    ),
                }

        except Exception as e:
            logger.error(f"Failed to get room with messages: {str(e)}")
            raise APIError("Failed to get room data")

    @staticmethod
    def send_message(
        user_id: str,
        room_id: int,
        content: str,
        message_type: str = "text",
        message_data: Optional[Dict[str, Any]] = None,
        product_id: Optional[str] = None,
    ) -> ChatMessage:
        """Send a message in a chat room

        Args:
            user_id: ID of the user sending the message
            room_id: ID of the chat room
            content: Message content
            message_type: Type of message (text, image, product, offer)
            message_data: Additional message data (for images, products, etc.)
            product_id: Optional product ID (for backward compatibility)

        Returns:
            ChatMessage object
        """
        try:
            with session_scope() as session:
                # Verify user has access to this room
                room = (
                    session.query(ChatRoom)
                    .filter(
                        ChatRoom.id == room_id,
                        db.or_(
                            ChatRoom.buyer_id == user_id,
                            ChatRoom.seller_id == user_id,
                        ),
                    )
                    .first()
                )

                if not room:
                    raise ForbiddenError("Access denied to this chat room")

                # Prepare message_data with product snapshot for product messages
                final_message_data = message_data or {}
                pid = product_id or final_message_data.get("product_id")
                if pid and "product_id" not in final_message_data:
                    final_message_data["product_id"] = pid

                # Enrich product messages with product snapshot (name, price, image_url)
                # so the frontend can render product cards without an extra API call
                if message_type == "product" and pid:
                    product_snapshot = ChatService._build_product_snapshot(pid, session)
                    if product_snapshot:
                        final_message_data["product"] = product_snapshot

                # Create message
                message = ChatMessage(
                    room_id=room_id,
                    sender_id=user_id,
                    content=content,
                    message_type=message_type,
                    message_data=final_message_data if final_message_data else None,
                )

                session.add(message)
                session.flush()

                # Update room's last message timestamp
                room.last_message_at = datetime.utcnow()

                # Update unread counts
                if room.buyer_id == user_id:
                    room.unread_count_seller += 1
                else:
                    room.unread_count_buyer += 1

                session.commit()

                return message

        except Exception as e:
            logger.error(f"Failed to send message: {str(e)}")
            raise APIError("Failed to send message")

    @staticmethod
    def send_offer(
        user_id: str, room_id: int, product_id: str, amount: float, message: str = ""
    ) -> Dict[str, Any]:
        """Send an offer in a chat room"""
        try:
            with session_scope() as session:
                # Verify user has access to this room
                room = (
                    session.query(ChatRoom)
                    .filter(
                        ChatRoom.id == room_id,
                        db.or_(
                            ChatRoom.buyer_id == user_id,
                            ChatRoom.seller_id == user_id,
                        ),
                    )
                    .first()
                )

                if not room:
                    raise ForbiddenError("Access denied to this chat room")

                # Get product details
                product = (
                    session.query(Product).filter(Product.id == product_id).first()
                )
                if not product:
                    raise NotFoundError("Product not found")

                # Create offer message
                message_data = {
                    "product_id": product_id,
                    "product_name": product.name,
                    "product_price": float(product.price),
                    "offer_amount": amount,
                    "offer_message": message,
                }

                chat_message = ChatMessage(
                    room_id=room_id,
                    sender_id=user_id,
                    content=f"Offered ${amount:.2f} for {product.name}",
                    message_type="offer",
                    message_data=message_data,
                )

                session.add(chat_message)
                session.flush()

                # Update room's last message timestamp
                room.last_message_at = datetime.utcnow()

                # Update unread counts
                if room.buyer_id == user_id:
                    room.unread_count_seller += 1
                else:
                    room.unread_count_buyer += 1

                session.commit()

                # Get sender info
                sender = session.query(User).filter(User.id == user_id).first()

                return {
                    "id": chat_message.id,
                    "content": chat_message.content,
                    "message_type": chat_message.message_type,
                    "message_data": chat_message.message_data,
                    "sender_id": chat_message.sender_id,
                    "sender_username": sender.username,
                    "is_read": chat_message.is_read,
                    "created_at": chat_message.created_at.isoformat(),
                }

        except Exception as e:
            logger.error(f"Failed to send offer: {str(e)}")
            raise APIError("Failed to send offer")

    @staticmethod
    def respond_to_offer(offer_id: int, user_id: str, response: str) -> Dict[str, Any]:
        """Respond to a chat offer (accept/reject)"""
        try:
            with session_scope() as session:
                # Get offer
                offer = (
                    session.query(ChatOffer)
                    .join(ChatMessage)
                    .filter(ChatOffer.id == offer_id)
                    .first()
                )

                if not offer:
                    raise NotFoundError("Offer not found")

                # Verify user can respond to this offer
                room = (
                    session.query(ChatRoom)
                    .filter(ChatRoom.id == offer.message.room_id)
                    .first()
                )

                if not room or (room.buyer_id != user_id and room.seller_id != user_id):
                    raise ForbiddenError("Access denied to this offer")

                # Update offer status
                offer.status = response  # "accepted" or "rejected"

                # Create response message
                response_message = ChatMessage(
                    room_id=room.id,
                    sender_id=user_id,
                    content=f"Offer {response}",
                    message_type="offer_response",
                    message_data={"offer_id": offer_id, "response": response},
                )

                session.add(response_message)
                session.flush()

                # Update room
                room.last_message_at = datetime.utcnow()
                session.commit()

                # Send real-time notification
                # ChatSocketManager.send_message_to_room(room.id, {
                #     "type": "offer_response",
                #     "message": {
                #         "id": response_message.id,
                #         "content": response_message.content,
                #         "message_type": "offer_response",
                #         "sender_id": response_message.sender_id,
                #         "created_at": response_message.created_at.isoformat(),
                #         "offer_response": {
                #             "offer_id": offer_id,
                #             "response": response,
                #         }
                #     }
                # })

                return {
                    "offer_id": offer_id,
                    "status": response,
                    "message": response_message,
                }

        except (ForbiddenError, NotFoundError):
            raise
        except Exception as e:
            logger.error(f"Failed to respond to offer: {str(e)}")
            raise APIError("Failed to respond to offer")

    @staticmethod
    def mark_messages_as_read(room_id: int, user_id: str) -> bool:
        """Mark all messages in a room as read for a user"""
        try:
            with session_scope() as session:
                # Verify user has access to this room
                room = (
                    session.query(ChatRoom)
                    .filter(
                        ChatRoom.id == room_id,
                        db.or_(
                            ChatRoom.buyer_id == user_id,
                            ChatRoom.seller_id == user_id,
                        ),
                    )
                    .first()
                )

                if not room:
                    raise ForbiddenError("Access denied to this chat room")

                # Mark messages as read
                unread_messages = (
                    session.query(ChatMessage)
                    .filter(
                        ChatMessage.room_id == room_id,
                        ChatMessage.sender_id != user_id,
                        ChatMessage.is_read == False,
                    )
                    .all()
                )

                for message in unread_messages:
                    message.is_read = True
                    message.read_at = datetime.utcnow()

                # Reset unread count
                if room.buyer_id == user_id:
                    room.unread_count_buyer = 0
                else:
                    room.unread_count_seller = 0

                session.commit()

                return True

        except ForbiddenError:
            raise
        except Exception as e:
            logger.error(f"Failed to mark messages as read: {str(e)}")
            raise APIError("Failed to mark messages as read")

    @staticmethod
    def set_typing_status(room_id: int, user_id: str, is_typing: bool) -> bool:
        """Set typing status for a user in a room"""
        try:
            # Verify user has access to this room
            with session_scope() as session:
                room = (
                    session.query(ChatRoom)
                    .filter(
                        ChatRoom.id == room_id,
                        db.or_(
                            ChatRoom.buyer_id == user_id,
                            ChatRoom.seller_id == user_id,
                        ),
                    )
                    .first()
                )

                if not room:
                    raise ForbiddenError("Access denied to this chat room")

            # Set typing status in Redis
            cache_key = ChatService.CACHE_KEYS["typing"].format(
                room_id=room_id, user_id=user_id
            )

            if is_typing:
                redis_client.setex(cache_key, 30, "typing")  # 30 seconds timeout
            else:
                redis_client.delete(cache_key)

            # Send real-time notification
            # ChatSocketManager.send_message_to_room(room_id, {
            #     "type": "typing_status",
            #     "user_id": user_id,
            #     "is_typing": is_typing,
            # })

            return True

        except ForbiddenError:
            raise
        except Exception as e:
            logger.error(f"Failed to set typing status: {str(e)}")
            raise APIError("Failed to set typing status")

    @staticmethod
    def set_online_status(user_id: str, is_online: bool) -> bool:
        """Set user's online status"""
        try:
            cache_key = ChatService.CACHE_KEYS["online_status"].format(user_id=user_id)

            if is_online:
                redis_client.setex(cache_key, 300, "online")  # 5 minutes timeout
            else:
                redis_client.delete(cache_key)

            return True

        except Exception as e:
            logger.error(f"Failed to set online status: {str(e)}")
            return False

    @staticmethod
    def get_online_status(user_id: str) -> bool:
        """Get user's online status"""
        try:
            cache_key = ChatService.CACHE_KEYS["online_status"].format(user_id=user_id)
            return redis_client.exists(cache_key) > 0
        except Exception as e:
            logger.error(f"Failed to get online status: {str(e)}")
            return False

    # Helper methods
    @staticmethod
    def _cache_user_room(user_id: str, room: ChatRoom):
        """Cache room for user"""
        try:
            cache_key = ChatService.CACHE_KEYS["user_rooms"].format(user_id=user_id)
            # This would cache the room data
        except Exception as e:
            logger.warning(f"Failed to cache user room: {str(e)}")

    @staticmethod
    def _get_unread_count(room_id: int, user_id: str) -> int:
        """Get unread message count for user in room"""
        try:
            with session_scope() as session:
                count = (
                    session.query(ChatMessage)
                    .filter(
                        ChatMessage.room_id == room_id,
                        ChatMessage.sender_id != user_id,
                        ChatMessage.is_read == False,
                    )
                    .count()
                )
                return count
        except Exception as e:
            logger.error(f"Failed to get unread count: {str(e)}")
            return 0

    @staticmethod
    def _mark_messages_as_read(room_id: int, user_id: str):
        """Mark messages as read for user in room"""
        try:
            with session_scope() as session:
                (
                    session.query(ChatMessage)
                    .filter(
                        ChatMessage.room_id == room_id,
                        ChatMessage.sender_id != user_id,
                        ChatMessage.is_read == False,
                    )
                    .update(
                        {
                            "is_read": True,
                            "read_at": datetime.utcnow(),
                        }
                    )
                )
                session.commit()
        except Exception as e:
            logger.error(f"Failed to mark messages as read: {str(e)}")


class ChatReactionService:
    """Service for managing reactions on chat messages"""

    @staticmethod
    def _emit_message_reaction_event(
        event: str,
        message_id: int,
        user_id: str,
        reaction_type: str,
        username: Optional[str] = None,
    ) -> None:
        """Emit reaction events from HTTP handlers (outside Socket.IO request context)."""
        from main.extensions import socketio

        reaction_value = (
            reaction_type.value if hasattr(reaction_type, "value") else reaction_type
        )
        socketio.emit(
            event,
            {
                "message_id": message_id,
                "user_id": user_id,
                "username": username or "User",
                "reaction_type": reaction_value,
                "timestamp": datetime.utcnow().isoformat(),
            },
            room=f"message_{message_id}",
            namespace="/chat",
        )

    @staticmethod
    def add_message_reaction(user_id: str, message_id: int, reaction_type: str):
        """Add or update a reaction on a chat message"""
        try:
            with session_scope() as session:
                # Check if message exists
                message = session.query(ChatMessage).get(message_id)
                if not message:
                    raise NotFoundError("Message not found")

                # Check if user already has this reaction
                existing_reaction = (
                    session.query(ChatMessageReaction)
                    .filter_by(
                        message_id=message_id,
                        user_id=user_id,
                        reaction_type=reaction_type,
                    )
                    .first()
                )

                if existing_reaction:
                    # User already has this reaction, return existing
                    return existing_reaction

                # Coerce string to enum (DB column is Enum(ReactionType))
                try:
                    reaction_type_enum = (
                        ReactionType(reaction_type)
                        if isinstance(reaction_type, str)
                        else reaction_type
                    )
                except ValueError:
                    raise ValidationError(
                        f"Invalid reaction_type: {reaction_type}",
                        status_code=400,
                    )

                # Create new reaction
                reaction = ChatMessageReaction(
                    message_id=message_id,
                    user_id=user_id,
                    reaction_type=reaction_type_enum,
                )
                session.add(reaction)
                session.commit()

                try:
                    user = session.query(User).filter(User.id == user_id).first()
                    ChatReactionService._emit_message_reaction_event(
                        "message_reaction_added",
                        message_id,
                        user_id,
                        reaction_type_enum,
                        username=user.username if user else None,
                    )
                    redis_client.hincrby(
                        f"message:{message_id}:reactions",
                        reaction_type_enum.value,
                        1,
                    )
                except Exception as e:
                    logger.warning("Failed to emit message_reaction_added event: %s", e)

                return reaction

        except (NotFoundError, ValidationError):
            raise
        except Exception as e:
            logger.error(
                "Failed to add message reaction: %s",
                str(e),
                exc_info=True,
            )
            raise APIError("Failed to add reaction", status_code=400)

    @staticmethod
    def remove_message_reaction(user_id: str, message_id: int, reaction_type: str):
        """Remove a reaction from a chat message"""
        try:
            with session_scope() as session:
                reaction = (
                    session.query(ChatMessageReaction)
                    .filter_by(
                        message_id=message_id,
                        user_id=user_id,
                        reaction_type=reaction_type,
                    )
                    .first()
                )

                if not reaction:
                    raise NotFoundError("Reaction not found")

                session.delete(reaction)
                session.commit()

                try:
                    user = session.query(User).filter(User.id == user_id).first()
                    ChatReactionService._emit_message_reaction_event(
                        "message_reaction_removed",
                        message_id,
                        user_id,
                        reaction_type,
                        username=user.username if user else None,
                    )
                    redis_client.hincrby(
                        f"message:{message_id}:reactions", reaction_type, -1
                    )
                except Exception as e:
                    logger.warning(
                        "Failed to emit message_reaction_removed event: %s", e
                    )

                return True

        except Exception as e:
            logger.error(f"Failed to remove message reaction: {str(e)}")
            raise APIError("Failed to remove reaction")

    @staticmethod
    def get_message_reactions(message_id: int, user_id: str = None):
        """Get all reactions for a chat message with counts and user's reactions"""
        try:
            with session_scope() as session:
                # Get all reactions for the message
                reactions = (
                    session.query(ChatMessageReaction)
                    .filter_by(message_id=message_id)
                    .all()
                )

                # Group by reaction type and count
                reaction_counts = {}
                user_reactions = set()

                for reaction in reactions:
                    reaction_type = reaction.reaction_type.value
                    reaction_counts[reaction_type] = (
                        reaction_counts.get(reaction_type, 0) + 1
                    )

                    if user_id and reaction.user_id == user_id:
                        user_reactions.add(reaction_type)

                # Format response
                result = []
                for reaction_type, count in reaction_counts.items():
                    result.append(
                        {
                            "reaction_type": reaction_type,
                            "count": count,
                            "has_reacted": reaction_type in user_reactions,
                        }
                    )

                return result

        except Exception as e:
            logger.error(f"Failed to get message reactions: {str(e)}")
            raise APIError("Failed to get reactions")


class DiscountService:
    """Service for managing discount offers within chat conversations"""

    # Cache keys for discount data
    CACHE_KEYS = {
        "user_discounts": "discount:user:{user_id}:active",
        "room_discounts": "discount:room:{room_id}:active",
        "discount_validation": "discount:validate:{discount_id}",
    }

    @staticmethod
    def create_discount_offer(
        seller_id: str, room_id: int, discount_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Create a new discount offer within a chat conversation

        Args:
            seller_id: ID of the seller creating the discount
            room_id: Chat room ID where discount is being offered
            discount_data: Discount configuration data

        Returns:
            Dict containing the created discount details
        """
        try:
            with session_scope() as session:
                # Validate seller permissions
                seller = (
                    session.query(User)
                    .filter(User.id == seller_id, User.seller_account.has())
                    .first()
                )

                if not seller:
                    raise ForbiddenError("Only sellers can create discount offers")

                # Validate room access and get room details
                room = (
                    session.query(ChatRoom)
                    .options(
                        joinedload(ChatRoom.buyer),
                        joinedload(ChatRoom.seller),
                        joinedload(ChatRoom.product),
                    )
                    .filter(ChatRoom.id == room_id, ChatRoom.seller_id == seller_id)
                    .first()
                )

                if not room:
                    raise ForbiddenError("Access denied to this chat room")

                # Validate discount data
                validation_result = DiscountService._validate_discount_data(
                    discount_data
                )
                if not validation_result["valid"]:
                    raise ValidationError(validation_result["message"])

                # Convert and store expires_at properly for database using timezone utilities
                from app.libs.datetime_utils import ensure_timezone_aware

                expires_at = ensure_timezone_aware(discount_data["expires_at"])

                # Create discount record
                discount = ChatDiscount(
                    room_id=room_id,
                    product_id=discount_data.get("product_id"),
                    discount_type=discount_data["discount_type"],
                    discount_value=discount_data["discount_value"],
                    minimum_order_amount=discount_data.get("minimum_order_amount"),
                    maximum_discount_amount=discount_data.get(
                        "maximum_discount_amount"
                    ),
                    expires_at=expires_at,
                    usage_limit=discount_data.get("usage_limit", 1),
                    created_by_id=seller_id,
                    offered_to_id=room.buyer_id,
                    discount_message=discount_data.get("discount_message"),
                    discount_code=discount_data.get("discount_code"),
                    discount_metadata=discount_data.get("metadata", {}),
                    status=DiscountStatus.PENDING,
                )

                session.add(discount)
                session.flush()

                # Create chat message for the discount offer
                message_content = DiscountService._generate_discount_message(
                    discount, room
                )
                message_data = {
                    "discount_id": discount.id,
                    "discount_type": discount.discount_type,
                    "discount_value": discount.discount_value,
                    "expires_at": discount.expires_at.isoformat(),
                    "product_id": discount.product_id,
                }

                chat_message = ChatMessage(
                    room_id=room_id,
                    sender_id=seller_id,
                    content=message_content,
                    message_type="discount",
                    message_data=message_data,
                )

                session.add(chat_message)
                session.flush()

                # Update discount with message reference
                discount.message_id = chat_message.id

                # Update room's last message timestamp
                room.last_message_at = datetime.utcnow()
                room.unread_count_buyer += 1

                session.commit()

                # Cache discount for quick access
                DiscountService._cache_discount(discount)

                # Prepare response data
                discount_response = {
                    "id": discount.id,
                    "message_id": chat_message.id,
                    "room_id": room_id,
                    "discount_type": discount.discount_type,
                    "discount_value": discount.discount_value,
                    "minimum_order_amount": discount.minimum_order_amount,
                    "maximum_discount_amount": discount.maximum_discount_amount,
                    "expires_at": discount.expires_at.isoformat(),
                    "usage_limit": discount.usage_limit,
                    "status": discount.status,
                    "discount_message": discount.discount_message,
                    "discount_code": discount.discount_code,
                    "created_at": discount.created_at.isoformat(),
                    "product": (
                        {
                            "id": room.product.id,
                            "name": room.product.name,
                            "price": float(room.product.price),
                        }
                        if room.product
                        else None
                    ),
                    "offered_to": {
                        "id": room.buyer.id,
                        "username": room.buyer.username,
                    },
                }

                # Emit real-time event for discount offer
                from app.realtime.event_manager import EventManager

                EventManager.emit_event(
                    event="discount_offered",
                    data={
                        "discount": discount_response,
                        "message": {
                            "id": chat_message.id,
                            "content": message_content,
                            "message_type": "discount",
                            "sender_id": seller_id,
                            "created_at": chat_message.created_at.isoformat(),
                        },
                    },
                    room=f"room_{room_id}",
                    namespace="/chat",
                    use_async=True,
                )

                return discount_response

        except (ValidationError, ForbiddenError, NotFoundError):
            raise
        except Exception as e:
            logger.error(f"Failed to create discount offer: {str(e)}")
            raise APIError("Failed to create discount offer")

    @staticmethod
    def respond_to_discount(
        buyer_id: str,
        discount_id: int,
        response: str,
        response_message: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Respond to a discount offer (accept/reject)

        Args:
            buyer_id: ID of the buyer responding
            discount_id: ID of the discount being responded to
            response: Response type ('accepted' or 'rejected')
            response_message: Optional custom response message

        Returns:
            Dict containing the response details
        """
        try:
            with session_scope() as session:
                # Get discount with room details
                discount = (
                    session.query(ChatDiscount)
                    .options(
                        joinedload(ChatDiscount.room),
                        joinedload(ChatDiscount.created_by),
                        joinedload(ChatDiscount.product),
                    )
                    .filter(
                        ChatDiscount.id == discount_id,
                        ChatDiscount.offered_to_id == buyer_id,
                    )
                    .first()
                )

                if not discount:
                    raise NotFoundError("Discount offer not found")

                if discount.status != DiscountStatus.PENDING:
                    raise ValidationError(
                        "Discount offer has already been responded to"
                    )

                # Validate response
                if response not in [DiscountStatus.ACCEPTED, DiscountStatus.REJECTED]:
                    raise ValidationError(
                        "Invalid response. Must be 'accepted' or 'rejected'"
                    )

                # Update discount status
                discount.status = response
                if response == DiscountStatus.ACCEPTED:
                    discount.accepted_at = datetime.utcnow()
                    discount.status = DiscountStatus.ACTIVE  # Make it available for use
                else:
                    discount.rejected_at = datetime.utcnow()

                # Create response message
                response_content = DiscountService._generate_response_message(
                    discount, response, response_message
                )

                message_data = {
                    "discount_id": discount_id,
                    "response": response,
                    "response_message": response_message,
                }

                response_chat_message = ChatMessage(
                    room_id=discount.room_id,
                    sender_id=buyer_id,
                    content=response_content,
                    message_type="discount_response",
                    message_data=message_data,
                )

                session.add(response_chat_message)

                # Update room's last message timestamp
                discount.room.last_message_at = datetime.utcnow()
                discount.room.unread_count_seller += 1

                session.commit()

                # Update cache
                DiscountService._cache_discount(discount)

                # Prepare response data
                response_data = {
                    "discount_id": discount_id,
                    "response": response,
                    "response_message": response_message,
                    "message_id": response_chat_message.id,
                    "updated_at": discount.updated_at.isoformat(),
                    "discount": {
                        "id": discount.id,
                        "status": discount.status,
                        "discount_type": discount.discount_type,
                        "discount_value": discount.discount_value,
                        "expires_at": discount.expires_at.isoformat(),
                    },
                }

                # Emit real-time event for discount response
                from app.realtime.event_manager import EventManager

                EventManager.emit_event(
                    event="discount_responded",
                    data={
                        "discount_response": response_data,
                        "message": {
                            "id": response_chat_message.id,
                            "content": response_content,
                            "message_type": "discount_response",
                            "sender_id": buyer_id,
                            "created_at": response_chat_message.created_at.isoformat(),
                        },
                    },
                    room=f"room_{discount.room_id}",
                    namespace="/chat",
                    use_async=True,
                )

                return response_data

        except (ValidationError, ForbiddenError, NotFoundError):
            raise
        except Exception as e:
            logger.error(f"Failed to respond to discount: {str(e)}")
            raise APIError("Failed to respond to discount")

    @staticmethod
    def get_active_discounts_for_user(
        user_id: str, room_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Get active discount offers for a user

        Args:
            user_id: ID of the user (buyer or seller)
            room_id: Optional room ID to filter discounts

        Returns:
            List of active discount offers
        """
        try:
            with session_scope() as session:
                query = (
                    session.query(ChatDiscount)
                    .options(
                        joinedload(ChatDiscount.room),
                        joinedload(ChatDiscount.created_by),
                        joinedload(ChatDiscount.offered_to),
                        joinedload(ChatDiscount.product),
                    )
                    .filter(
                        ChatDiscount.status.in_(
                            [
                                DiscountStatus.PENDING,
                                DiscountStatus.ACTIVE,
                                DiscountStatus.ACCEPTED,
                            ]
                        ),
                        ChatDiscount.expires_at > datetime.utcnow(),
                    )
                )

                # Filter by user role and room
                if room_id:
                    query = query.filter(ChatDiscount.room_id == room_id)
                else:
                    # Get discounts where user is either buyer or seller
                    query = query.filter(
                        db.or_(
                            ChatDiscount.offered_to_id == user_id,
                            ChatDiscount.created_by_id == user_id,
                        )
                    )

                discounts = query.order_by(ChatDiscount.created_at.desc()).all()

                # Format response
                formatted_discounts = []
                for discount in discounts:
                    formatted_discounts.append(
                        {
                            "id": discount.id,
                            "room_id": discount.room_id,
                            "discount_type": discount.discount_type,
                            "discount_value": discount.discount_value,
                            "minimum_order_amount": discount.minimum_order_amount,
                            "maximum_discount_amount": discount.maximum_discount_amount,
                            "expires_at": discount.expires_at.isoformat(),
                            "usage_limit": discount.usage_limit,
                            "usage_count": discount.usage_count,
                            "status": discount.status,
                            "discount_message": discount.discount_message,
                            "discount_code": discount.discount_code,
                            "created_at": discount.created_at.isoformat(),
                            "is_valid": discount.is_valid(),
                            "product": (
                                {
                                    "id": discount.product.id,
                                    "name": discount.product.name,
                                    "price": float(discount.product.price),
                                }
                                if discount.product
                                else None
                            ),
                            "created_by": {
                                "id": discount.created_by.id,
                                "username": discount.created_by.username,
                            },
                            "offered_to": {
                                "id": discount.offered_to.id,
                                "username": discount.offered_to.username,
                            },
                        }
                    )

                return formatted_discounts

        except Exception as e:
            logger.error(f"Failed to get active discounts: {str(e)}")
            raise APIError("Failed to get active discounts")

    @staticmethod
    def apply_discount_to_order(
        user_id: str, discount_id: int, order_amount: float
    ) -> Tuple[bool, float, str]:
        """
        Apply a discount to an order (validate and calculate discount amount)

        Args:
            user_id: ID of the user applying the discount
            discount_id: ID of the discount to apply
            order_amount: Amount of the order

        Returns:
            Tuple of (success, discount_amount, message)
        """
        try:
            with session_scope() as session:
                # Get discount
                discount = (
                    session.query(ChatDiscount)
                    .filter(
                        ChatDiscount.id == discount_id,
                        ChatDiscount.offered_to_id == user_id,
                    )
                    .first()
                )

                if not discount:
                    return False, 0.0, "Discount not found"

                # Validate discount can be applied
                can_apply, message = discount.can_be_applied_to_order(order_amount)
                if not can_apply:
                    return False, 0.0, message

                # Calculate discount amount
                discount_amount = discount.calculate_discount_amount(order_amount)

                # Update usage count
                discount.usage_count += 1
                if discount.usage_count >= discount.usage_limit:
                    discount.status = DiscountStatus.USED
                    discount.used_at = datetime.utcnow()

                session.commit()

                # Update cache
                DiscountService._cache_discount(discount)

                # Emit real-time event for discount usage
                from app.realtime.event_manager import EventManager

                EventManager.emit_event(
                    event="discount_applied",
                    data={
                        "discount_id": discount_id,
                        "user_id": user_id,
                        "order_amount": order_amount,
                        "discount_amount": discount_amount,
                        "remaining_usage": discount.usage_limit - discount.usage_count,
                    },
                    room=f"room_{discount.room_id}",
                    namespace="/chat",
                    use_async=True,
                )

                return True, discount_amount, "Discount applied successfully"

        except Exception as e:
            logger.error(f"Failed to apply discount: {str(e)}")
            return False, 0.0, "Failed to apply discount"

    @staticmethod
    def cancel_discount(seller_id: str, discount_id: int) -> Dict[str, Any]:
        """
        Cancel a discount offer (seller only)

        Args:
            seller_id: ID of the seller cancelling the discount
            discount_id: ID of the discount to cancel

        Returns:
            Dict containing cancellation details
        """
        try:
            with session_scope() as session:
                # Get discount
                discount = (
                    session.query(ChatDiscount)
                    .filter(
                        ChatDiscount.id == discount_id,
                        ChatDiscount.created_by_id == seller_id,
                        ChatDiscount.status.in_(
                            [DiscountStatus.PENDING, DiscountStatus.ACTIVE]
                        ),
                    )
                    .first()
                )

                if not discount:
                    raise NotFoundError("Discount not found or cannot be cancelled")

                # Update status
                discount.status = DiscountStatus.CANCELLED
                session.commit()

                # Update cache
                DiscountService._cache_discount(discount)

                # Emit real-time event for discount cancellation
                from app.realtime.event_manager import EventManager

                EventManager.emit_event(
                    event="discount_cancelled",
                    data={
                        "discount_id": discount_id,
                        "cancelled_by": seller_id,
                        "cancelled_at": datetime.utcnow().isoformat(),
                    },
                    room=f"room_{discount.room_id}",
                    namespace="/chat",
                    use_async=True,
                )

                return {
                    "discount_id": discount_id,
                    "status": DiscountStatus.CANCELLED,
                    "cancelled_at": datetime.utcnow().isoformat(),
                }

        except (NotFoundError, ForbiddenError):
            raise
        except Exception as e:
            logger.error(f"Failed to cancel discount: {str(e)}")
            raise APIError("Failed to cancel discount")

    # Helper methods
    @staticmethod
    def _validate_discount_data(discount_data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate discount creation data"""
        required_fields = ["discount_type", "discount_value", "expires_at"]

        for field in required_fields:
            if field not in discount_data:
                return {"valid": False, "message": f"Missing required field: {field}"}

        # Validate discount type
        if discount_data["discount_type"] not in [
            DiscountType.PERCENTAGE,
            DiscountType.FIXED_AMOUNT,
        ]:
            return {"valid": False, "message": "Invalid discount type"}

        # Validate discount value
        discount_value = discount_data["discount_value"]
        if discount_value <= 0:
            return {"valid": False, "message": "Discount value must be greater than 0"}

        if (
            discount_data["discount_type"] == DiscountType.PERCENTAGE
            and discount_value > 100
        ):
            return {"valid": False, "message": "Percentage discount cannot exceed 100%"}

        # Validate expiry date using timezone-safe utilities
        from app.libs.datetime_utils import (
            ensure_timezone_aware,
            utcnow_aware,
            is_past_datetime,
        )

        try:
            expires_at = ensure_timezone_aware(discount_data["expires_at"])
        except (ValueError, TypeError):
            return {"valid": False, "message": "Invalid expiry date format"}

        if is_past_datetime(expires_at):
            return {"valid": False, "message": "Expiry date must be in the future"}

        # Validate minimum order amount
        min_order = discount_data.get("minimum_order_amount")
        if min_order is not None and min_order <= 0:
            return {
                "valid": False,
                "message": "Minimum order amount must be greater than 0",
            }

        # Validate maximum discount amount
        max_discount = discount_data.get("maximum_discount_amount")
        if max_discount is not None and max_discount <= 0:
            return {
                "valid": False,
                "message": "Maximum discount amount must be greater than 0",
            }

        return {"valid": True, "message": "Valid discount data"}

    @staticmethod
    def _generate_discount_message(discount: ChatDiscount, room: ChatRoom) -> str:
        """Generate a human-readable discount offer message"""
        product_name = room.product.name if room.product else "your order"

        if discount.discount_type == DiscountType.PERCENTAGE:
            discount_text = f"{discount.discount_value}% off"
        else:
            discount_text = f"${discount.discount_value:.2f} off"

        message = f"🎉 Special discount offer: {discount_text} on {product_name}!"

        if discount.minimum_order_amount:
            message += f" (Minimum order: ${discount.minimum_order_amount:.2f})"

        if discount.discount_message:
            message += f"\n\n{discount.discount_message}"

        message += (
            f"\n\n⏰ Expires: {discount.expires_at.strftime('%B %d, %Y at %I:%M %p')}"
        )

        return message

    @staticmethod
    def _generate_response_message(
        discount: ChatDiscount, response: str, custom_message: Optional[str] = None
    ) -> str:
        """Generate a response message for discount acceptance/rejection"""
        if response == DiscountStatus.ACCEPTED:
            message = f"✅ Accepted your discount offer!"
            if custom_message:
                message += f" {custom_message}"
        else:
            message = f"❌ Thank you for the offer, but I'll pass for now."
            if custom_message:
                message += f" {custom_message}"

        return message

    @staticmethod
    def _cache_discount(discount: ChatDiscount):
        """Cache discount data for quick access"""
        try:
            cache_key = DiscountService.CACHE_KEYS["discount_validation"].format(
                discount_id=discount.id
            )

            cache_data = {
                "id": discount.id,
                "status": discount.status,
                "expires_at": discount.expires_at.isoformat(),
                "usage_count": discount.usage_count,
                "usage_limit": discount.usage_limit,
                "is_valid": discount.is_valid(),
            }

            redis_client.setex(cache_key, 3600, str(cache_data))  # 1 hour cache
        except Exception as e:
            logger.warning(f"Failed to cache discount: {str(e)}")
