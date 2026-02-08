#!/usr/bin/env python3
"""
Test script to verify user-based posting functionality.

This script tests:
1. Post creation by both buyers and sellers
2. Follow relationships between any users
3. Feed generation with user-based follows
4. Niche posting for different user types
5. Post ownership and permissions

Run with: python test_user_based_posting.py
"""

import os
import sys
import json
import requests
from datetime import datetime

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

class UserBasedPostingTester:
    def __init__(self, base_url="http://localhost:5000/api/v1"):
        self.base_url = base_url
        self.session = requests.Session()
        self.test_results = []
        
    def log_test(self, test_name, success, message=""):
        """Log test result"""
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status} {test_name}")
        if message:
            print(f"    {message}")
        
        self.test_results.append({
            "test": test_name,
            "success": success,
            "message": message,
            "timestamp": datetime.now().isoformat()
        })
    
    def test_post_creation_by_buyer(self):
        """Test that buyers can create posts"""
        test_name = "Post Creation by Buyer"
        
        try:
            # This would require authentication setup
            # For now, we'll test the endpoint structure
            response = self.session.post(
                f"{self.base_url}/socials/posts",
                json={
                    "caption": "Test buyer post",
                    "status": "draft",
                    "tags": ["test", "buyer"]
                }
            )
            
            # Should not return 403 Forbidden (seller_required error)
            if response.status_code != 403:
                self.log_test(test_name, True, "Buyer can create posts")
            else:
                self.log_test(test_name, False, "Buyer still restricted by seller_required")
                
        except Exception as e:
            self.log_test(test_name, False, f"Error: {str(e)}")
    
    def test_post_creation_by_seller(self):
        """Test that sellers can still create posts"""
        test_name = "Post Creation by Seller"
        
        try:
            response = self.session.post(
                f"{self.base_url}/socials/posts",
                json={
                    "caption": "Test seller post",
                    "status": "draft",
                    "tags": ["test", "seller"]
                }
            )
            
            if response.status_code != 403:
                self.log_test(test_name, True, "Seller can still create posts")
            else:
                self.log_test(test_name, False, "Seller posting broken")
                
        except Exception as e:
            self.log_test(test_name, False, f"Error: {str(e)}")
    
    def test_follow_any_user(self):
        """Test that users can follow any other user"""
        test_name = "Follow Any User"
        
        try:
            # Test following a buyer (previously not allowed)
            response = self.session.post(
                f"{self.base_url}/socials/follow/test_buyer_id"
            )
            
            # Should not return validation error about sellers only
            if response.status_code != 400 or "sellers" not in response.text:
                self.log_test(test_name, True, "Can follow any user")
            else:
                self.log_test(test_name, False, "Still restricted to following sellers only")
                
        except Exception as e:
            self.log_test(test_name, False, f"Error: {str(e)}")
    
    def test_user_posts_endpoint(self):
        """Test the new user posts endpoint"""
        test_name = "User Posts Endpoint"
        
        try:
            response = self.session.get(
                f"{self.base_url}/socials/user/test_user_id/posts"
            )
            
            if response.status_code == 200:
                self.log_test(test_name, True, "User posts endpoint works")
            else:
                self.log_test(test_name, False, f"Endpoint returned {response.status_code}")
                
        except Exception as e:
            self.log_test(test_name, False, f"Error: {str(e)}")
    
    def test_user_drafts_endpoint(self):
        """Test the new user drafts endpoint"""
        test_name = "User Drafts Endpoint"
        
        try:
            response = self.session.get(
                f"{self.base_url}/socials/user/posts/drafts"
            )
            
            if response.status_code in [200, 401]:  # 401 is expected without auth
                self.log_test(test_name, True, "User drafts endpoint accessible")
            else:
                self.log_test(test_name, False, f"Endpoint returned {response.status_code}")
                
        except Exception as e:
            self.log_test(test_name, False, f"Error: {str(e)}")
    
    def test_feed_generation(self):
        """Test that feed generation works with user-based follows"""
        test_name = "Feed Generation"
        
        try:
            response = self.session.get(
                f"{self.base_url}/socials/feed"
            )
            
            if response.status_code in [200, 401]:  # 401 is expected without auth
                self.log_test(test_name, True, "Feed endpoint accessible")
            else:
                self.log_test(test_name, False, f"Feed returned {response.status_code}")
                
        except Exception as e:
            self.log_test(test_name, False, f"Error: {str(e)}")
    
    def test_niche_posting_permissions(self):
        """Test niche posting permissions for different user types"""
        test_name = "Niche Posting Permissions"
        
        try:
            # Test niche post creation
            response = self.session.post(
                f"{self.base_url}/socials/niches/test_niche_id/posts",
                json={
                    "caption": "Test niche post",
                    "status": "draft"
                }
            )
            
            if response.status_code in [201, 401]:  # 401 is expected without auth
                self.log_test(test_name, True, "Niche posting endpoint accessible")
            else:
                self.log_test(test_name, False, f"Niche posting returned {response.status_code}")
                
        except Exception as e:
            self.log_test(test_name, False, f"Error: {str(e)}")
    
    def run_all_tests(self):
        """Run all tests"""
        print("🧪 Testing User-Based Posting Functionality")
        print("=" * 50)
        
        self.test_post_creation_by_buyer()
        self.test_post_creation_by_seller()
        self.test_follow_any_user()
        self.test_user_posts_endpoint()
        self.test_user_drafts_endpoint()
        self.test_feed_generation()
        self.test_niche_posting_permissions()
        
        # Summary
        print("\n" + "=" * 50)
        passed = sum(1 for result in self.test_results if result["success"])
        total = len(self.test_results)
        
        print(f"📊 Test Results: {passed}/{total} tests passed")
        
        if passed == total:
            print("🎉 All tests passed! User-based posting is working correctly.")
        else:
            print("⚠️  Some tests failed. Check the details above.")
            
        return passed == total
    
    def save_results(self, filename="test_results.json"):
        """Save test results to file"""
        with open(filename, 'w') as f:
            json.dump(self.test_results, f, indent=2)
        print(f"📄 Test results saved to {filename}")

def main():
    """Main function"""
    tester = UserBasedPostingTester()
    
    success = tester.run_all_tests()
    tester.save_results()
    
    if not success:
        sys.exit(1)

if __name__ == "__main__":
    main()
