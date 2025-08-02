"""
Category data definitions for the ecommerce platform.

This file contains all the category and subcategory data used by management commands.
Separating this data makes it easier to maintain and allows for reuse across different commands.
"""

# Main Categories (Level 1) - Standard ecommerce categories
MAIN_CATEGORIES = [
    {
        "name": "Electronics",
        "description": "Electronic devices and accessories",
        "slug": "electronics",
        "parent_id": None,
    },
    {
        "name": "Fashion",
        "description": "Clothing, shoes, and accessories",
        "slug": "fashion",
        "parent_id": None,
    },
    {
        "name": "Home & Garden",
        "description": "Home improvement and garden supplies",
        "slug": "home-garden",
        "parent_id": None,
    },
    {
        "name": "Sports & Outdoors",
        "description": "Sports equipment and outdoor activities",
        "slug": "sports-outdoors",
        "parent_id": None,
    },
    {
        "name": "Books & Media",
        "description": "Books, movies, music, and digital media",
        "slug": "books-media",
        "parent_id": None,
    },
    {
        "name": "Health & Beauty",
        "description": "Health products and beauty supplies",
        "slug": "health-beauty",
        "parent_id": None,
    },
    {
        "name": "Toys & Games",
        "description": "Toys, games, and entertainment",
        "slug": "toys-games",
        "parent_id": None,
    },
    {
        "name": "Automotive",
        "description": "Car parts, accessories, and maintenance",
        "slug": "automotive",
        "parent_id": None,
    },
    {
        "name": "Food & Beverages",
        "description": "Food, drinks, and consumables",
        "slug": "food-beverages",
        "parent_id": None,
    },
    {
        "name": "Jewelry & Watches",
        "description": "Fine jewelry and timepieces",
        "slug": "jewelry-watches",
        "parent_id": None,
    },
    {
        "name": "Art & Collectibles",
        "description": "Artwork, antiques, and collectible items",
        "slug": "art-collectibles",
        "parent_id": None,
    },
    {
        "name": "Baby & Kids",
        "description": "Products for babies and children",
        "slug": "baby-kids",
        "parent_id": None,
    },
    {
        "name": "Pet Supplies",
        "description": "Pet food, toys, and accessories",
        "slug": "pet-supplies",
        "parent_id": None,
    },
    {
        "name": "Office & Business",
        "description": "Office supplies and business equipment",
        "slug": "office-business",
        "parent_id": None,
    },
    {
        "name": "Music & Instruments",
        "description": "Musical instruments and equipment",
        "slug": "music-instruments",
        "parent_id": None,
    },
    # Social Commerce Specific Categories
    {
        "name": "Digital Products",
        "description": "Digital downloads, software, and online services",
        "slug": "digital-products",
        "parent_id": None,
    },
    {
        "name": "Handmade & Crafts",
        "description": "Handcrafted items and DIY creations",
        "slug": "handmade-crafts",
        "parent_id": None,
    },
    {
        "name": "Vintage & Second-hand",
        "description": "Vintage items and pre-owned goods",
        "slug": "vintage-secondhand",
        "parent_id": None,
    },
    {
        "name": "Educational & Courses",
        "description": "Online courses, tutorials, and educational content",
        "slug": "educational-courses",
        "parent_id": None,
    },
    {
        "name": "Local & Regional",
        "description": "Location-specific products and services",
        "slug": "local-regional",
        "parent_id": None,
    },
]

# Subcategories (Level 2) - Organized by parent category
SUBCATEGORIES = [
    # Electronics subcategories
    {
        "name": "Smartphones",
        "description": "Mobile phones and accessories",
        "slug": "smartphones",
        "parent_name": "Electronics",
    },
    {
        "name": "Laptops & Computers",
        "description": "Computers, laptops, and accessories",
        "slug": "laptops-computers",
        "parent_name": "Electronics",
    },
    {
        "name": "Audio & Video",
        "description": "Speakers, headphones, and video equipment",
        "slug": "audio-video",
        "parent_name": "Electronics",
    },
    {
        "name": "Gaming",
        "description": "Gaming consoles, games, and accessories",
        "slug": "gaming",
        "parent_name": "Electronics",
    },
    {
        "name": "Cameras & Photography",
        "description": "Cameras, lenses, and photography equipment",
        "slug": "cameras-photography",
        "parent_name": "Electronics",
    },
    {
        "name": "Smart Home",
        "description": "Smart home devices and automation",
        "slug": "smart-home",
        "parent_name": "Electronics",
    },
    # Fashion subcategories
    {
        "name": "Men's Clothing",
        "description": "Clothing for men",
        "slug": "mens-clothing",
        "parent_name": "Fashion",
    },
    {
        "name": "Women's Clothing",
        "description": "Clothing for women",
        "slug": "womens-clothing",
        "parent_name": "Fashion",
    },
    {
        "name": "Kids' Clothing",
        "description": "Clothing for children",
        "slug": "kids-clothing",
        "parent_name": "Fashion",
    },
    {
        "name": "Shoes",
        "description": "Footwear for all ages",
        "slug": "shoes",
        "parent_name": "Fashion",
    },
    {
        "name": "Accessories",
        "description": "Bags, jewelry, and fashion accessories",
        "slug": "accessories",
        "parent_name": "Fashion",
    },
    {
        "name": "Vintage Fashion",
        "description": "Vintage and retro clothing",
        "slug": "vintage-fashion",
        "parent_name": "Fashion",
    },
    # Home & Garden subcategories
    {
        "name": "Furniture",
        "description": "Home and office furniture",
        "slug": "furniture",
        "parent_name": "Home & Garden",
    },
    {
        "name": "Kitchen & Dining",
        "description": "Kitchen appliances and dining items",
        "slug": "kitchen-dining",
        "parent_name": "Home & Garden",
    },
    {
        "name": "Garden & Outdoor",
        "description": "Garden tools and outdoor furniture",
        "slug": "garden-outdoor",
        "parent_name": "Home & Garden",
    },
    {
        "name": "Home Decor",
        "description": "Decorative items for home",
        "slug": "home-decor",
        "parent_name": "Home & Garden",
    },
    {
        "name": "Tools & Hardware",
        "description": "DIY tools and hardware supplies",
        "slug": "tools-hardware",
        "parent_name": "Home & Garden",
    },
    # Sports & Outdoors subcategories
    {
        "name": "Fitness & Exercise",
        "description": "Exercise equipment and fitness gear",
        "slug": "fitness-exercise",
        "parent_name": "Sports & Outdoors",
    },
    {
        "name": "Team Sports",
        "description": "Equipment for team sports",
        "slug": "team-sports",
        "parent_name": "Sports & Outdoors",
    },
    {
        "name": "Outdoor Recreation",
        "description": "Camping, hiking, and outdoor gear",
        "slug": "outdoor-recreation",
        "parent_name": "Sports & Outdoors",
    },
    {
        "name": "Water Sports",
        "description": "Swimming, surfing, and water activities",
        "slug": "water-sports",
        "parent_name": "Sports & Outdoors",
    },
    {
        "name": "Cycling",
        "description": "Bicycles and cycling accessories",
        "slug": "cycling",
        "parent_name": "Sports & Outdoors",
    },
    # Health & Beauty subcategories
    {
        "name": "Skincare",
        "description": "Facial and body skincare products",
        "slug": "skincare",
        "parent_name": "Health & Beauty",
    },
    {
        "name": "Makeup",
        "description": "Cosmetics and makeup products",
        "slug": "makeup",
        "parent_name": "Health & Beauty",
    },
    {
        "name": "Hair Care",
        "description": "Hair products and styling tools",
        "slug": "hair-care",
        "parent_name": "Health & Beauty",
    },
    {
        "name": "Personal Care",
        "description": "Personal hygiene and care products",
        "slug": "personal-care",
        "parent_name": "Health & Beauty",
    },
    {
        "name": "Health & Wellness",
        "description": "Vitamins, supplements, and health products",
        "slug": "health-wellness",
        "parent_name": "Health & Beauty",
    },
    {
        "name": "Natural & Organic",
        "description": "Natural and organic beauty products",
        "slug": "natural-organic",
        "parent_name": "Health & Beauty",
    },
    # Books & Media subcategories
    {
        "name": "Books",
        "description": "Physical and digital books",
        "slug": "books",
        "parent_name": "Books & Media",
    },
    {
        "name": "Movies & TV",
        "description": "DVDs, Blu-rays, and streaming content",
        "slug": "movies-tv",
        "parent_name": "Books & Media",
    },
    {
        "name": "Music",
        "description": "CDs, vinyl records, and digital music",
        "slug": "music",
        "parent_name": "Books & Media",
    },
    {
        "name": "Magazines & Newspapers",
        "description": "Periodicals and publications",
        "slug": "magazines-newspapers",
        "parent_name": "Books & Media",
    },
    {
        "name": "Digital Downloads",
        "description": "E-books, digital music, and software",
        "slug": "digital-downloads",
        "parent_name": "Books & Media",
    },
    # Toys & Games subcategories
    {
        "name": "Board Games",
        "description": "Traditional board games and puzzles",
        "slug": "board-games",
        "parent_name": "Toys & Games",
    },
    {
        "name": "Video Games",
        "description": "Video games and gaming accessories",
        "slug": "video-games",
        "parent_name": "Toys & Games",
    },
    {
        "name": "Educational Toys",
        "description": "Learning toys and educational games",
        "slug": "educational-toys",
        "parent_name": "Toys & Games",
    },
    {
        "name": "Action Figures",
        "description": "Collectible action figures and dolls",
        "slug": "action-figures",
        "parent_name": "Toys & Games",
    },
    {
        "name": "Building & Construction",
        "description": "LEGO, building blocks, and construction toys",
        "slug": "building-construction",
        "parent_name": "Toys & Games",
    },
    # Automotive subcategories
    {
        "name": "Car Parts",
        "description": "Automotive parts and components",
        "slug": "car-parts",
        "parent_name": "Automotive",
    },
    {
        "name": "Car Accessories",
        "description": "Car interior and exterior accessories",
        "slug": "car-accessories",
        "parent_name": "Automotive",
    },
    {
        "name": "Motorcycle Parts",
        "description": "Motorcycle parts and accessories",
        "slug": "motorcycle-parts",
        "parent_name": "Automotive",
    },
    {
        "name": "Tools & Equipment",
        "description": "Automotive tools and diagnostic equipment",
        "slug": "automotive-tools",
        "parent_name": "Automotive",
    },
    {
        "name": "Car Care",
        "description": "Car cleaning and maintenance products",
        "slug": "car-care",
        "parent_name": "Automotive",
    },
    # Food & Beverages subcategories
    {
        "name": "Snacks & Candy",
        "description": "Snacks, candies, and treats",
        "slug": "snacks-candy",
        "parent_name": "Food & Beverages",
    },
    {
        "name": "Beverages",
        "description": "Drinks, juices, and beverages",
        "slug": "beverages",
        "parent_name": "Food & Beverages",
    },
    {
        "name": "Organic & Natural",
        "description": "Organic and natural food products",
        "slug": "organic-natural",
        "parent_name": "Food & Beverages",
    },
    {
        "name": "Gourmet & Specialty",
        "description": "Gourmet foods and specialty items",
        "slug": "gourmet-specialty",
        "parent_name": "Food & Beverages",
    },
    {
        "name": "Local & Artisanal",
        "description": "Local and artisanal food products",
        "slug": "local-artisanal",
        "parent_name": "Food & Beverages",
    },
    # Jewelry & Watches subcategories
    {
        "name": "Fine Jewelry",
        "description": "Precious metals and gemstone jewelry",
        "slug": "fine-jewelry",
        "parent_name": "Jewelry & Watches",
    },
    {
        "name": "Fashion Jewelry",
        "description": "Costume and fashion jewelry",
        "slug": "fashion-jewelry",
        "parent_name": "Jewelry & Watches",
    },
    {
        "name": "Watches",
        "description": "Luxury and fashion timepieces",
        "slug": "watches",
        "parent_name": "Jewelry & Watches",
    },
    {
        "name": "Wedding & Engagement",
        "description": "Wedding rings and engagement jewelry",
        "slug": "wedding-engagement",
        "parent_name": "Jewelry & Watches",
    },
    {
        "name": "Artisanal Jewelry",
        "description": "Handcrafted and artisanal jewelry",
        "slug": "artisanal-jewelry",
        "parent_name": "Jewelry & Watches",
    },
    # Art & Collectibles subcategories
    {
        "name": "Fine Art",
        "description": "Paintings, sculptures, and fine art",
        "slug": "fine-art",
        "parent_name": "Art & Collectibles",
    },
    {
        "name": "Antiques",
        "description": "Antique furniture and collectibles",
        "slug": "antiques",
        "parent_name": "Art & Collectibles",
    },
    {
        "name": "Trading Cards & Figurines",
        "description": "Trading cards, figurines, and collectibles",
        "slug": "trading-cards-figurines",
        "parent_name": "Art & Collectibles",
    },
    {
        "name": "Crafts & DIY",
        "description": "Handmade crafts and DIY supplies",
        "slug": "crafts-diy",
        "parent_name": "Art & Collectibles",
    },
    {
        "name": "Vintage Art",
        "description": "Vintage artwork and prints",
        "slug": "vintage-art",
        "parent_name": "Art & Collectibles",
    },
    # Baby & Kids subcategories
    {
        "name": "Baby Care",
        "description": "Baby food, diapers, and care products",
        "slug": "baby-care",
        "parent_name": "Baby & Kids",
    },
    {
        "name": "Baby Gear",
        "description": "Strollers, car seats, and baby equipment",
        "slug": "baby-gear",
        "parent_name": "Baby & Kids",
    },
    {
        "name": "Kids Toys",
        "description": "Toys for children of all ages",
        "slug": "kids-toys",
        "parent_name": "Baby & Kids",
    },
    {
        "name": "School Supplies",
        "description": "Backpacks, stationery, and school items",
        "slug": "school-supplies",
        "parent_name": "Baby & Kids",
    },
    {
        "name": "Kids Clothing",
        "description": "Clothing for babies and children",
        "slug": "baby-kids-clothing",
        "parent_name": "Baby & Kids",
    },
    # Pet Supplies subcategories
    {
        "name": "Dog Supplies",
        "description": "Food, toys, and accessories for dogs",
        "slug": "dog-supplies",
        "parent_name": "Pet Supplies",
    },
    {
        "name": "Cat Supplies",
        "description": "Food, toys, and accessories for cats",
        "slug": "cat-supplies",
        "parent_name": "Pet Supplies",
    },
    {
        "name": "Fish & Aquatic",
        "description": "Aquarium supplies and fish care",
        "slug": "fish-aquatic",
        "parent_name": "Pet Supplies",
    },
    {
        "name": "Bird & Small Pets",
        "description": "Supplies for birds and small animals",
        "slug": "bird-small-pets",
        "parent_name": "Pet Supplies",
    },
    {
        "name": "Pet Health",
        "description": "Pet health and wellness products",
        "slug": "pet-health",
        "parent_name": "Pet Supplies",
    },
    # Office & Business subcategories
    {
        "name": "Office Supplies",
        "description": "Paper, pens, and office essentials",
        "slug": "office-supplies",
        "parent_name": "Office & Business",
    },
    {
        "name": "Business Equipment",
        "description": "Printers, scanners, and office equipment",
        "slug": "business-equipment",
        "parent_name": "Office & Business",
    },
    {
        "name": "Furniture & Storage",
        "description": "Office furniture and storage solutions",
        "slug": "office-furniture",
        "parent_name": "Office & Business",
    },
    {
        "name": "Business Services",
        "description": "Professional services and consulting",
        "slug": "business-services",
        "parent_name": "Office & Business",
    },
    # Music & Instruments subcategories
    {
        "name": "String Instruments",
        "description": "Guitars, violins, and string instruments",
        "slug": "string-instruments",
        "parent_name": "Music & Instruments",
    },
    {
        "name": "Percussion",
        "description": "Drums, cymbals, and percussion instruments",
        "slug": "percussion",
        "parent_name": "Music & Instruments",
    },
    {
        "name": "Wind Instruments",
        "description": "Flutes, saxophones, and wind instruments",
        "slug": "wind-instruments",
        "parent_name": "Music & Instruments",
    },
    {
        "name": "Audio Equipment",
        "description": "Amplifiers, microphones, and recording gear",
        "slug": "audio-equipment",
        "parent_name": "Music & Instruments",
    },
    {
        "name": "Sheet Music",
        "description": "Sheet music and music books",
        "slug": "sheet-music",
        "parent_name": "Music & Instruments",
    },
    # Digital Products subcategories
    {
        "name": "Software & Apps",
        "description": "Software applications and mobile apps",
        "slug": "software-apps",
        "parent_name": "Digital Products",
    },
    {
        "name": "Digital Art",
        "description": "Digital artwork, graphics, and designs",
        "slug": "digital-art",
        "parent_name": "Digital Products",
    },
    {
        "name": "Templates & Themes",
        "description": "Website templates, themes, and designs",
        "slug": "templates-themes",
        "parent_name": "Digital Products",
    },
    {
        "name": "E-books & Guides",
        "description": "Digital books, guides, and manuals",
        "slug": "ebooks-guides",
        "parent_name": "Digital Products",
    },
    {
        "name": "Online Services",
        "description": "Web services, consulting, and digital services",
        "slug": "online-services",
        "parent_name": "Digital Products",
    },
    # Handmade & Crafts subcategories
    {
        "name": "Handcrafted Jewelry",
        "description": "Handcrafted jewelry and accessories",
        "slug": "handcrafted-jewelry",
        "parent_name": "Handmade & Crafts",
    },
    {
        "name": "Handmade Clothing",
        "description": "Handcrafted clothing and textiles",
        "slug": "handmade-clothing",
        "parent_name": "Handmade & Crafts",
    },
    {
        "name": "Home Decor Crafts",
        "description": "Handmade home decor and crafts",
        "slug": "home-decor-crafts",
        "parent_name": "Handmade & Crafts",
    },
    {
        "name": "Craft Supplies",
        "description": "Materials and supplies for crafting",
        "slug": "craft-supplies",
        "parent_name": "Handmade & Crafts",
    },
    {
        "name": "DIY Kits",
        "description": "Do-it-yourself craft kits and projects",
        "slug": "diy-kits",
        "parent_name": "Handmade & Crafts",
    },
    # Vintage & Second-hand subcategories
    {
        "name": "Vintage Clothing",
        "description": "Vintage and retro clothing",
        "slug": "vintage-clothing",
        "parent_name": "Vintage & Second-hand",
    },
    {
        "name": "Vintage Electronics",
        "description": "Vintage electronics and gadgets",
        "slug": "vintage-electronics",
        "parent_name": "Vintage & Second-hand",
    },
    {
        "name": "Vintage Furniture",
        "description": "Vintage and antique furniture",
        "slug": "vintage-furniture",
        "parent_name": "Vintage & Second-hand",
    },
    {
        "name": "Vintage Collectibles",
        "description": "Vintage collectibles and memorabilia",
        "slug": "vintage-collectibles",
        "parent_name": "Vintage & Second-hand",
    },
    {
        "name": "Second-hand Books",
        "description": "Used books and literature",
        "slug": "secondhand-books",
        "parent_name": "Vintage & Second-hand",
    },
    # Educational & Courses subcategories
    {
        "name": "Online Courses",
        "description": "Video courses and tutorials",
        "slug": "online-courses",
        "parent_name": "Educational & Courses",
    },
    {
        "name": "Tutoring Services",
        "description": "One-on-one tutoring and coaching",
        "slug": "tutoring-services",
        "parent_name": "Educational & Courses",
    },
    {
        "name": "Study Materials",
        "description": "Notes, guides, and study resources",
        "slug": "study-materials",
        "parent_name": "Educational & Courses",
    },
    {
        "name": "Language Learning",
        "description": "Language courses and materials",
        "slug": "language-learning",
        "parent_name": "Educational & Courses",
    },
    {
        "name": "Skill Development",
        "description": "Professional and personal development courses",
        "slug": "skill-development",
        "parent_name": "Educational & Courses",
    },
    # Local & Regional subcategories
    {
        "name": "Local Food",
        "description": "Local and regional food products",
        "slug": "local-food",
        "parent_name": "Local & Regional",
    },
    {
        "name": "Local Crafts",
        "description": "Local artisans and craftspeople",
        "slug": "local-crafts",
        "parent_name": "Local & Regional",
    },
    {
        "name": "Local Services",
        "description": "Local business services",
        "slug": "local-services",
        "parent_name": "Local & Regional",
    },
    {
        "name": "Regional Products",
        "description": "Products specific to regions",
        "slug": "regional-products",
        "parent_name": "Local & Regional",
    },
]
