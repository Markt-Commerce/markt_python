from flask import request, jsonify
from flask_smorest import Blueprint
from flask_socketio import emit, join_room, leave_room
from flask_login import current_user, login_required
from sqlalchemy.exc import SQLAlchemyError
from .. import socketio, db
from ..models.user_model import User
from ..models.chat_model import ChatMessage, ChatRoom
from ..models.product_model import Product
from ..schemas import ChatMessageSchema, ChatRoomSchema
from cryptography.fernet import Fernet
import os

# Blueprint for Chat functionality
chat_bp = Blueprint("chat", __name__, description="Chat operations")

# Generate encryption key (use a persistent key in production)
encryption_key = os.environ.get("CHAT_ENCRYPTION_KEY") or Fernet.generate_key()
cipher = Fernet(encryption_key)


@socketio.on("connect")
@login_required
def handle_connect():
    emit("connected", {"data": f"Connected as {current_user.id}"})


@socketio.on("join")
@login_required
def on_join(data):
    room = data["room"]
    join_room(room)
    emit("status", {"msg": f"User {current_user.id} has entered the room."}, room=room)


@socketio.on("leave")
@login_required
def on_leave(data):
    room = data["room"]
    leave_room(room)
    emit("status", {"msg": f"User {current_user.id} has left the room."}, room=room)


@socketio.on("message")
@login_required
def handle_message(data):
    room = data["room"]
    message = data["message"]

    try:
        # Encrypt the message
        encrypted_message = cipher.encrypt(message.encode())

        chat_message = ChatMessage(
            sender_id=current_user.id,
            room_id=room,
            content=encrypted_message,  # Store encrypted message
        )
        db.session.add(chat_message)
        db.session.commit()

        emit(
            "message",
            {
                "user": current_user.id,
                "msg": message,  # Send plain text back to room for display
            },
            room=room,
        )

    except SQLAlchemyError:
        db.session.rollback()
        emit("error", {"msg": "Failed to save message"}, room=room)


@socketio.on("product_share")
@login_required
def handle_product_share(data):
    room = data["room"]
    product_id = data["product_id"]

    product = Product.query.get(product_id)
    if product:
        try:
            # Encrypt the product share message
            product_share_message = f"Shared product: {product.name}"
            encrypted_message = cipher.encrypt(product_share_message.encode())

            chat_message = ChatMessage(
                sender_id=current_user.id,
                room_id=room,
                content=encrypted_message,  # Store encrypted product share
                is_product_share=True,
                product_id=product_id,
            )
            db.session.add(chat_message)
            db.session.commit()

            emit(
                "product_shared",
                {
                    "user": current_user.id,
                    "product": {
                        "id": product.id,
                        "name": product.name,
                        "price": product.price,
                        "description": product.description,
                        "image_url": product.image_url,  # Assuming you have an image_url field
                    },
                },
                room=room,
            )

        except SQLAlchemyError:
            db.session.rollback()
            emit("error", {"msg": "Failed to share product"}, room=room)
    else:
        emit("error", {"msg": "Product not found"}, room=room)


@chat_bp.route("/rooms", methods=["POST"])
@login_required
def create_chat_room():
    data = request.json
    buyer_id = data.get("buyer_id")
    seller_id = data.get("seller_id")

    if current_user.id != buyer_id and current_user.id != seller_id:
        return jsonify({"error": "Unauthorized"}), 403

    try:
        chat_room = ChatRoom(buyer_id=buyer_id, seller_id=seller_id)
        db.session.add(chat_room)
        db.session.commit()
        return ChatRoomSchema().dump(chat_room), 201
    except SQLAlchemyError:
        db.session.rollback()
        return jsonify({"error": "Failed to create chat room"}), 500


@chat_bp.route("/rooms/<int:room_id>/messages", methods=["GET"])
@login_required
def get_chat_messages(room_id):
    chat_room = ChatRoom.query.get(room_id)

    if not chat_room or (
        current_user.id != chat_room.buyer_id and current_user.id != chat_room.seller_id
    ):
        return jsonify({"error": "Unauthorized"}), 403

    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)

    messages = (
        ChatMessage.query.filter_by(room_id=room_id)
        .order_by(ChatMessage.timestamp.desc())
        .paginate(page=page, per_page=per_page)
    )

    # Decrypt messages before sending
    decrypted_messages = []
    for message in messages.items:
        decrypted_content = cipher.decrypt(message.content).decode()
        decrypted_messages.append(
            {
                "id": message.id,
                "sender_id": message.sender_id,
                "content": decrypted_content,
                "timestamp": message.timestamp,
                "is_product_share": message.is_product_share,
                "product_id": message.product_id,
            }
        )

    return jsonify(
        {
            "messages": decrypted_messages,
            "total": messages.total,
            "pages": messages.pages,
            "current_page": messages.page,
        }
    )
