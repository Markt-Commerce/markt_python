# Category Management Commands

This directory contains management commands for populating and managing the categories table in your ecommerce platform.

## Structure

```
app/categories/
├── management/
│   ├── __init__.py
│   ├── data.py                    # Category data definitions
│   └── commands/
│       ├── __init__.py
│       ├── populate_categories.py # Populate categories command
│       ├── list_categories.py     # List categories command
│       └── clear_categories.py    # Clear categories command
├── models.py                      # Category models
├── routes.py                      # Category API routes
├── services.py                    # Category business logic
├── schemas.py                     # Category serialization schemas
└── README.md                      # This file
```

## Available Commands

### 1. Populate Categories
Populates the database with standard ecommerce categories and subcategories.

```bash
# Populate categories (will skip if categories already exist)
flask populate-categories

# Force recreation of categories (will delete existing ones)
flask populate-categories --force
```

### 2. List Categories
Displays all categories in a hierarchical format.

```bash
flask list-categories
```

### 3. Clear Categories
Removes all categories from the database.

```bash
# Interactive confirmation
flask clear-categories

# Skip confirmation
flask clear-categories --confirm
```

## Category Structure

The management command creates a comprehensive category hierarchy with:

### Main Categories (20 total):
- Electronics
- Fashion
- Home & Garden
- Sports & Outdoors
- Books & Media
- Health & Beauty
- Toys & Games
- Automotive
- Food & Beverages
- Jewelry & Watches
- Art & Collectibles
- Baby & Kids
- Pet Supplies
- Office & Business
- Music & Instruments
- **Digital Products** (Social Commerce)
- **Handmade & Crafts** (Social Commerce)
- **Vintage & Second-hand** (Social Commerce)
- **Educational & Courses** (Student Entrepreneurs)
- **Local & Regional** (Location-based)

### Subcategories (100+ total):
Each main category has 4-6 relevant subcategories covering the most common ecommerce product types, with special focus on social commerce and student entrepreneur needs.

## Usage Examples

```bash
# First time setup - populate categories
flask populate-categories

# Check what categories were created
flask list-categories

# If you need to reset categories
flask clear-categories --confirm
flask populate-categories

# Update existing categories (force recreation)
flask populate-categories --force
```

## Category Model Features

Each category includes:
- **Name**: Human-readable category name
- **Description**: Detailed description of the category
- **Slug**: URL-friendly identifier
- **Parent ID**: For hierarchical relationships
- **Active Status**: To enable/disable categories
- **Metadata**: JSONB field for additional attributes

## Integration

These categories are automatically available for:
- Product categorization
- Social media posts
- Buyer requests
- Seller profiles
- Niche communities

The category system supports flexible relationships across all major entities in your social commerce platform.
