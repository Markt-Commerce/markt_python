# Categories Module - Postman Test Guide

## 🎯 **Overview**

This guide provides comprehensive testing scenarios for the Categories module endpoints. The module handles category hierarchy, product categorization, and tag management.

## 📋 **Available Endpoints**

### **Base URL**: `http://localhost:8000/api/v1/categories`

---

## 🗂️ **Category Management Endpoints**

### **1. Get Category Hierarchy**
```http
GET /categories/
```

**Description**: Retrieves the complete category tree with hierarchical structure

**Response Example**:
```json
[
  {
    "id": 1,
    "name": "Electronics",
    "slug": "electronics",
    "image_url": "https://example.com/electronics.jpg",
    "children": [
      {
        "id": 2,
        "name": "Smartphones",
        "slug": "smartphones",
        "image_url": "https://example.com/smartphones.jpg",
        "children": []
      },
      {
        "id": 3,
        "name": "Laptops",
        "slug": "laptops",
        "image_url": "https://example.com/laptops.jpg",
        "children": []
      }
    ]
  },
  {
    "id": 4,
    "name": "Fashion",
    "slug": "fashion",
    "image_url": "https://example.com/fashion.jpg",
    "children": [
      {
        "id": 5,
        "name": "Men's Clothing",
        "slug": "mens-clothing",
        "image_url": "https://example.com/mens-clothing.jpg",
        "children": []
      }
    ]
  }
]
```

**Test Scenarios**:
- ✅ **Happy Path**: Should return all active categories in tree structure
- ✅ **Empty Categories**: Should return empty array if no categories exist
- ✅ **Performance**: Should respond within 200ms

---

### **2. Get Category Details**
```http
GET /categories/{category_id}
```

**Description**: Retrieves detailed information about a specific category

**Test Cases**:

#### **Case 1: Valid Category ID**
```http
GET /categories/1
```

**Expected Response**:
```json
{
  "id": 1,
  "name": "Electronics",
  "description": "All electronic devices and gadgets",
  "slug": "electronics",
  "image_url": "https://example.com/electronics.jpg",
  "is_active": true,
  "parent_id": null
}
```

#### **Case 2: Invalid Category ID**
```http
GET /categories/999
```

**Expected Response**:
```json
{
  "message": "Category not found",
  "status": 404
}
```

---

### **3. Create New Category**
```http
POST /categories/
Authorization: Bearer <admin_token>
Content-Type: application/json
```

**Test Cases**:

#### **Case 1: Create Root Category**
```json
{
  "name": "Home & Garden",
  "description": "Everything for your home and garden",
  "is_active": true
}
```

**Expected Response**:
```json
{
  "id": 6,
  "name": "Home & Garden",
  "description": "Everything for your home and garden",
  "slug": "home-garden",
  "image_url": null,
  "is_active": true,
  "parent_id": null
}
```

#### **Case 2: Create Subcategory**
```json
{
  "name": "Kitchen Appliances",
  "description": "Kitchen tools and appliances",
  "parent_id": 6,
  "is_active": true
}
```

**Expected Response**:
```json
{
  "id": 7,
  "name": "Kitchen Appliances",
  "description": "Kitchen tools and appliances",
  "slug": "kitchen-appliances",
  "image_url": null,
  "is_active": true,
  "parent_id": 6
}
```

#### **Case 3: Duplicate Category Name**
```json
{
  "name": "Electronics",
  "description": "Duplicate category name"
}
```

**Expected Response**:
```json
{
  "message": "Category with this name already exists",
  "status": 400
}
```

#### **Case 4: Invalid Parent ID**
```json
{
  "name": "Test Category",
  "parent_id": 999
}
```

**Expected Response**:
```json
{
  "message": "Parent category not found",
  "status": 400
}
```

---

### **4. Update Category**
```http
PUT /categories/{category_id}
Authorization: Bearer <admin_token>
Content-Type: application/json
```

**Test Cases**:

#### **Case 1: Update Category Name**
```http
PUT /categories/1
```
```json
{
  "name": "Electronics & Gadgets",
  "description": "Updated description for electronics"
}
```

**Expected Response**:
```json
{
  "id": 1,
  "name": "Electronics & Gadgets",
  "description": "Updated description for electronics",
  "slug": "electronics-gadgets",
  "image_url": "https://example.com/electronics.jpg",
  "is_active": true,
  "parent_id": null
}
```

#### **Case 2: Deactivate Category**
```http
PUT /categories/1
```
```json
{
  "is_active": false
}
```

**Expected Response**:
```json
{
  "id": 1,
  "name": "Electronics & Gadgets",
  "description": "Updated description for electronics",
  "slug": "electronics-gadgets",
  "image_url": "https://example.com/electronics.jpg",
  "is_active": false,
  "parent_id": null
}
```

---

### **5. Get Category Products**
```http
GET /categories/{category_id}/products?page=1&per_page=20
```

**Description**: Retrieves paginated list of products in a specific category

**Test Cases**:

#### **Case 1: Category with Products**
```http
GET /categories/1/products?page=1&per_page=10
```

**Expected Response**:
```json
{
  "category": {
    "id": 1,
    "name": "Electronics",
    "description": "All electronic devices and gadgets",
    "slug": "electronics",
    "image_url": "https://example.com/electronics.jpg",
    "is_active": true,
    "parent_id": null
  },
  "products": [
    {
      "id": "PROD_12345678",
      "name": "iPhone 15 Pro",
      "description": "Latest iPhone with advanced features",
      "price": 1299.99,
      "status": "active",
      "seller": {
        "id": 1,
        "name": "TechStore",
        "user": {
          "id": "USER_123",
          "username": "techstore"
        }
      }
    }
  ],
  "pagination": {
    "page": 1,
    "per_page": 10,
    "total_items": 25,
    "total_pages": 3
  }
}
```

#### **Case 2: Empty Category**
```http
GET /categories/999/products
```

**Expected Response**:
```json
{
  "message": "Category not found",
  "status": 404
}
```

#### **Case 3: Pagination Test**
```http
GET /categories/1/products?page=2&per_page=5
```

**Expected Response**:
```json
{
  "category": {
    "id": 1,
    "name": "Electronics",
    "description": "All electronic devices and gadgets",
    "slug": "electronics",
    "image_url": "https://example.com/electronics.jpg",
    "is_active": true,
    "parent_id": null
  },
  "products": [
    // Products 6-10
  ],
  "pagination": {
    "page": 2,
    "per_page": 5,
    "total_items": 25,
    "total_pages": 5
  }
}
```

---

## 🏷️ **Tag Management Endpoints**

### **6. Get Popular Tags**
```http
GET /categories/tags
```

**Description**: Retrieves most used product tags

**Expected Response**:
```json
[
  {
    "id": 1,
    "name": "Smartphone",
    "slug": "smartphone",
    "description": "Mobile phones and smartphones"
  },
  {
    "id": 2,
    "name": "Laptop",
    "slug": "laptop",
    "description": "Portable computers"
  },
  {
    "id": 3,
    "name": "Wireless",
    "slug": "wireless",
    "description": "Wireless devices and accessories"
  }
]
```

---

### **7. Create New Tag**
```http
POST /categories/tags
Authorization: Bearer <admin_token>
Content-Type: application/json
```

**Test Cases**:

#### **Case 1: Create New Tag**
```json
{
  "name": "Gaming",
  "description": "Gaming accessories and equipment"
}
```

**Expected Response**:
```json
{
  "id": 4,
  "name": "Gaming",
  "slug": "gaming",
  "description": "Gaming accessories and equipment"
}
```

#### **Case 2: Duplicate Tag Name**
```json
{
  "name": "Smartphone",
  "description": "Duplicate tag name"
}
```

**Expected Response**:
```json
{
  "message": "Tag with this name already exists",
  "status": 400
}
```

---

## 🔧 **Test Data Setup**

### **Sample Categories for Testing**
```sql
-- Insert test categories
INSERT INTO categories (id, name, description, slug, is_active) VALUES
(1, 'Electronics', 'All electronic devices and gadgets', 'electronics', true),
(2, 'Smartphones', 'Mobile phones and smartphones', 'smartphones', true),
(3, 'Laptops', 'Portable computers and laptops', 'laptops', true),
(4, 'Fashion', 'Clothing and fashion accessories', 'fashion', true),
(5, 'Men''s Clothing', 'Clothing for men', 'mens-clothing', true);

-- Set parent relationships
UPDATE categories SET parent_id = 1 WHERE id IN (2, 3);
UPDATE categories SET parent_id = 4 WHERE id = 5;
```

### **Sample Tags for Testing**
```sql
-- Insert test tags
INSERT INTO tags (id, name, slug, description) VALUES
(1, 'Smartphone', 'smartphone', 'Mobile phones and smartphones'),
(2, 'Laptop', 'laptop', 'Portable computers'),
(3, 'Wireless', 'wireless', 'Wireless devices and accessories'),
(4, 'Gaming', 'gaming', 'Gaming accessories and equipment');
```

---

## 🧪 **Comprehensive Test Scenarios**

### **Scenario 1: Complete Category Management Flow**
1. **Create Root Category**
   ```http
   POST /categories/
   ```
   ```json
   {
     "name": "Sports & Fitness",
     "description": "Sports equipment and fitness gear"
   }
   ```

2. **Create Subcategories**
   ```http
   POST /categories/
   ```
   ```json
   {
     "name": "Running",
     "description": "Running shoes and accessories",
     "parent_id": 6
   }
   ```

3. **Verify Hierarchy**
   ```http
   GET /categories/
   ```

4. **Update Category**
   ```http
   PUT /categories/6
   ```
   ```json
   {
     "description": "Updated sports and fitness equipment"
   }
   ```

5. **Get Category Details**
   ```http
   GET /categories/6
   ```

### **Scenario 2: Tag Management Flow**
1. **Create Tags**
   ```http
   POST /categories/tags
   ```
   ```json
   {
     "name": "Premium",
     "description": "Premium quality products"
   }
   ```

2. **Get Popular Tags**
   ```http
   GET /categories/tags
   ```

3. **Create Duplicate Tag (Should Fail)**
   ```http
   POST /categories/tags
   ```
   ```json
   {
     "name": "Premium",
     "description": "Duplicate tag"
   }
   ```

### **Scenario 3: Error Handling**
1. **Invalid Category ID**
   ```http
   GET /categories/999
   ```

2. **Create Category with Invalid Parent**
   ```http
   POST /categories/
   ```
   ```json
   {
     "name": "Test Category",
     "parent_id": 999
   }
   ```

3. **Update Non-existent Category**
   ```http
   PUT /categories/999
   ```
   ```json
   {
     "name": "Updated Name"
   }
   ```

---

## 📊 **Performance Testing**

### **Load Testing Scenarios**
1. **Category Tree Loading**
   ```bash
   # Test with 100 concurrent users
   ab -n 1000 -c 100 http://localhost:8000/api/v1/categories/
   ```

2. **Category Products Loading**
   ```bash
   # Test pagination performance
   ab -n 500 -c 50 "http://localhost:8000/api/v1/categories/1/products?page=1&per_page=20"
   ```

### **Expected Performance Metrics**
- **Category Tree**: < 100ms response time
- **Category Details**: < 50ms response time
- **Category Products**: < 200ms response time
- **Tag List**: < 50ms response time

---

## 🔍 **Validation Checklist**

### **Functional Validation**
- [ ] Category hierarchy displays correctly
- [ ] Parent-child relationships work properly
- [ ] Pagination works for category products
- [ ] Error handling for invalid IDs
- [ ] Duplicate name prevention
- [ ] Category activation/deactivation
- [ ] Tag creation and retrieval
- [ ] Popular tags sorting

### **Data Validation**
- [ ] Required fields are validated
- [ ] Unique constraints are enforced
- [ ] Foreign key relationships are maintained
- [ ] Data integrity is preserved

### **Security Validation**
- [ ] Admin-only endpoints require authentication
- [ ] Input sanitization prevents injection
- [ ] Rate limiting is applied
- [ ] CORS headers are set correctly

---

## 🚀 **Quick Test Commands**

### **Using curl**
```bash
# Get category tree
curl -X GET http://localhost:8000/api/v1/categories/

# Get category details
curl -X GET http://localhost:8000/api/v1/categories/1

# Create category
curl -X POST http://localhost:8000/api/v1/categories/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{"name": "Test Category", "description": "Test description"}'

# Get category products
curl -X GET "http://localhost:8000/api/v1/categories/1/products?page=1&per_page=10"

# Get popular tags
curl -X GET http://localhost:8000/api/v1/categories/tags
```

### **Using Postman**
1. Import the collection
2. Set up environment variables
3. Run the test scenarios in order
4. Verify all responses match expected format
5. Check error handling scenarios

---

## ✅ **Success Criteria**

The Categories module is working correctly when:
- ✅ All endpoints return proper HTTP status codes
- ✅ Category hierarchy displays correctly
- ✅ Pagination works for category products
- ✅ Error handling works for invalid inputs
- ✅ Admin-only endpoints require authentication
- ✅ Performance meets expected metrics
- ✅ Data validation prevents invalid inputs
- ✅ All test scenarios pass successfully

---

**Note**: This test guide covers all the functionality of the Categories module. Make sure to test both happy path scenarios and error conditions to ensure robust functionality. 