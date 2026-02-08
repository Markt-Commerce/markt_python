"""
Test Authentication Setup for Chat Discount Testing

This script creates test users and sets up authentication for testing the chat discount system.
Run this before using the test client.
"""

from main.setup import create_app
from app.users.models import User, Seller, Buyer
from app.products.models import Product
from app.chats.models import ChatRoom
from external.database import db
from flask_login import login_user
import requests

def create_test_data():
    """Create test users, products, and chat rooms for testing"""
    app = create_app()
    
    with app.app_context():
        try:
            # Create test seller
            seller_user = User.query.filter_by(username="test_seller").first()
            if not seller_user:
                seller_user = User(
                    username="test_seller",
                    email="seller@test.com",
                    password_hash="test_hash",
                    is_email_verified=True
                )
                db.session.add(seller_user)
                db.session.flush()
                
                seller_account = Seller(
                    user_id=seller_user.id,
                    business_name="Test Store",
                    verification_status="verified"
                )
                db.session.add(seller_account)
            
            # Create test buyer
            buyer_user = User.query.filter_by(username="test_buyer").first()
            if not buyer_user:
                buyer_user = User(
                    username="test_buyer", 
                    email="buyer@test.com",
                    password_hash="test_hash",
                    is_email_verified=True
                )
                db.session.add(buyer_user)
                db.session.flush()
                
                buyer_account = Buyer(
                    user_id=buyer_user.id
                )
                db.session.add(buyer_account)
            
            # Create test product
            test_product = Product.query.filter_by(sku="TEST_PRODUCT").first()
            if not test_product:
                test_product = Product(
                    name="Test Product",
                    description="A test product for discount testing",
                    price=100.00,
                    stock=10,
                    sku="TEST_PRODUCT",
                    seller_id=seller_user.seller_account.id
                )
                db.session.add(test_product)
            
            # Create test chat room
            test_room = ChatRoom.query.filter_by(
                buyer_id=buyer_user.id,
                seller_id=seller_user.id
            ).first()
            if not test_room:
                test_room = ChatRoom(
                    buyer_id=buyer_user.id,
                    seller_id=seller_user.id,
                    product_id=test_product.id
                )
                db.session.add(test_room)
            
            db.session.commit()
            
            print("✅ Test data created successfully!")
            print(f"📊 Test Room ID: {test_room.id}")
            print(f"👤 Seller User ID: {seller_user.id}")
            print(f"👤 Buyer User ID: {buyer_user.id}")
            print(f"🛍️ Product ID: {test_product.id}")
            
            return {
                "room_id": test_room.id,
                "seller_id": seller_user.id,
                "buyer_id": buyer_user.id,
                "product_id": test_product.id
            }
            
        except Exception as e:
            print(f"❌ Error creating test data: {e}")
            db.session.rollback()
            return None

if __name__ == "__main__":
    test_data = create_test_data()
    if test_data:
        print("\n🎯 Use these IDs in your test client:")
        print(f"Room ID: {test_data['room_id']}")
        print(f"Seller ID: {test_data['seller_id']}")
        print(f"Buyer ID: {test_data['buyer_id']}")
        print(f"Product ID: {test_data['product_id']}")


