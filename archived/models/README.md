### Database Schema

#### Seller Table

| Column Name    | Data Type        | Constraints                  | Description                                       |
| ---------------|------------------|------------------------------|---------------------------------------------------|
| id             | INT              | AUTO_INCREMENT, PRIMARY KEY  | Unique identifier for each seller.                |
| unique_id      | VARCHAR(400)     | NOT NULL                     | Unique identifier for the seller.                |
| shopname       | VARCHAR(255)     | NOT NULL                     | Name of the seller's shop.                       |
| password       | VARCHAR(255)     | NOT NULL                     | Seller's password (hashed and salted).           |
| email          | VARCHAR(255)     | NOT NULL                     | Seller's email address.                           |
| longitude      | FLOAT            | NOT NULL                     | Seller's longitude location.                     |
| latitude       | FLOAT            | NOT NULL                     | Seller's latitude location.                      |
| phone_number   | VARCHAR(255)     | NOT NULL                     | Seller's contact phone number.                   |
| description    | VARCHAR(400)     | NOT NULL                     | Description of the seller's shop.               |
| category       | VARCHAR(255)     | NOT NULL                     | Category of the seller's shop.                  |
| total_rating   | INT              | NOT NULL                     | Total rating of the seller.                      |
| total_raters   | INT              | NOT NULL                     | Total number of raters.                          |
| directions     | VARCHAR(400)     | NOT NULL                     | Directions to the seller's shop.                |
| profile_image  | VARCHAR(400)     | NOT NULL                     | URL or path to the seller's profile image.       |
| house_number   | INT              | NOT NULL                     | Seller's house number.                            |
| street         | VARCHAR(255)     | NOT NULL                     | Seller's street address.                         |
| city           | VARCHAR(255)     | NOT NULL                     | Seller's city.                                   |
| state          | VARCHAR(255)     | NOT NULL                     | Seller's state.                                  |
| country        | VARCHAR(255)     | NOT NULL                     | Seller's country.                                |
| postal_code    | INT              | NOT NULL                     | Seller's postal code.                            |

#### Buyers Table

| Column Name    | Data Type  | Constraints                   | Description                                       |
| ---------------|------------|-------------------------------|---------------------------------------------------|
| id             | INT        | PRIMARY KEY, AUTO_INCREMENT   | Unique identifier for each buyer.                |
| unique_id      | VARCHAR(400) | NOT NULL                     | Unique identifier for the buyer.                |
| username       | VARCHAR(255) | NOT NULL                     | Buyer's username.                                |
| password       | VARCHAR(255) | NOT NULL                     | Buyer's password (hashed and salted).            |
| email          | VARCHAR(255) | NOT NULL                     | Buyer's email address.                            |
| longitude      | FLOAT      | NOT NULL                     | Buyer's longitude location.                      |
| latitude       | FLOAT      | NOT NULL                     | Buyer's latitude location.                       |
| profile_image  | VARCHAR(400) | NOT NULL                     | URL or path to the buyer's profile image.        |
| phone_number   | VARCHAR(255) | NOT NULL                     | Buyer's contact phone number.                    |
| house_number   | INT        | NOT NULL                     | Buyer's house number.                            |
| street         | VARCHAR(255) | NOT NULL                     | Buyer's street address.                         |
| city           | VARCHAR(255) | NOT NULL                     | Buyer's city.                                   |
| state          | VARCHAR(255) | NOT NULL                     | Buyer's state.                                  |
| country        | VARCHAR(255) | NOT NULL                     | Buyer's country.                                |
| postal_code    | INT        | NOT NULL                     | Buyer's postal code.                            |
| user_type      | VARCHAR(255) | NOT NULL                     | Type of user (e.g., seller or buyer).           |
| user_status    | VARCHAR(255) | DEFAULT 'active'             | Status of the user account (e.g., active, disabled). |

#### Cart Table

| Column Name    | Data Type  | Constraints                   | Description                                       |
| ---------------|------------|-------------------------------|---------------------------------------------------|
| id             | INT        | PRIMARY KEY, AUTO_INCREMENT   | Unique identifier for each cart item.            |
| cart_id        | VARCHAR(400) | NOT NULL                     | Unique identifier for the cart.                 |
| buyer_id       | VARCHAR(400) | NOT NULL                     | Unique identifier for the buyer.                |
| product_id     | VARCHAR(400) | NOT NULL                     | Unique identifier for the product.              |
| quantity       | INT        | NOT NULL                     | Quantity of the product in the cart.            |
| has_discount   | BOOLEAN    | NOT NULL                     | Indicates if the product has a discount.        |
| discount_price | FLOAT      | NOT NULL                     | Discounted price of the product.                |
| discount_percent | FLOAT    | NOT NULL                     | Discount percentage of the product.            |
| order_status   | VARCHAR(255) | DEFAULT 'pending'            | Status of the order associated with the cart.   |

#### Order Table

| Column Name    | Data Type  | Constraints                   | Description                                       |
| ---------------|------------|-------------------------------|---------------------------------------------------|
| id             | INT        | PRIMARY KEY, AUTO_INCREMENT   | Unique identifier for each order.                |
| buyer_id       | VARCHAR(400) | NOT NULL                     | Unique identifier for the buyer.                |
| seller_id      | VARCHAR(400) | NOT NULL                     | Unique identifier for the seller.               |
| product_id     | VARCHAR(400) | NOT NULL                     | Unique identifier for the product.              |
| quantity       | INT        | NOT NULL                     | Quantity of the product in the order.           |
| total_price    | FLOAT      | NOT NULL                     | Total price of the order.                       |
| order_status   | VARCHAR(255) | DEFAULT 'pending'            | Status of the order (e.g., pending, shipped).   |
| order_date     | TIMESTAMP  | NOT NULL                     | Date and time when the order was placed.       |
| delivery_address | VARCHAR(400) | NOT NULL                   | Delivery address for the order.                 |

#### Payment Table

| Column Name    | Data Type        | Constraints                  | Description                                       |
| ---------------|------------------|------------------------------|---------------------------------------------------|
| id             | INT              | AUTO_INCREMENT, PRIMARY KEY  | Unique identifier for each payment.              |
| payment_id     | VARCHAR(400)     | NOT NULL                     | Unique identifier for the payment.              |
| order_id       | VARCHAR(400)     | NOT NULL                     | Unique identifier for the order.                |
| payment_method | VARCHAR(255)     | NOT NULL                     | Payment method used (e.g., credit card).        |
| amount         | FLOAT            | NOT NULL                     | Payment amount.                                  |
| payment_status | VARCHAR(255)     | NOT NULL                     | Status of the payment (e.g., success, failed).  |
| payment_date   | DATETIME         | NOT NULL                     | Date and time when the payment was made.       |

#### Product Table

| Column Name    | Data Type  | Constraints                   | Description                                       |
| ---------------|------------|-------------------------------|---------------------------------------------------|
| id             | INT        | PRIMARY KEY, AUTO_INCREMENT   | Unique identifier for each product.              |
| seller_id      | VARCHAR(400) | NOT NULL                     | Unique identifier for the seller.               |
| name           | VARCHAR(255) | NOT NULL                     | Name of the product.                            |
| description    | VARCHAR(400) | NOT NULL                     | Description of the product.                     |
| price          | FLOAT      | NOT NULL                     | Price of the product.                           |
| stock_quantity | INT        | NOT NULL                     | Available quantity of the product in stock.    |
| category       | VARCHAR(255) | NOT NULL                     | Category of the product.                        |
| product_image  | VARCHAR(400) | NOT NULL                     | URL or path to the product image.               |


#### BuyerRequest Table
| Column Name    | Data Type  | Constraints                   | Description                                       |
| ---------------|------------|-------------------------------|---------------------------------------------------|
| id             | INT        | PRIMARY KEY, AUTO_INCREMENT   | Unique identifier for each request.              |
| buyer_id       | VARCHAR(400) | NOT NULL                     | Unique identifier for the buyer making the request. |
| product_description | VARCHAR(400) | NOT NULL                 | Description of the requested product.           |
| category       | VARCHAR(255) |                             | Category of the requested product.              |
| created_at     | TIMESTAMP  | NOT NULL                     | Timestamp when the request was created.         |
| status         | VARCHAR(255) | DEFAULT 'open'               | Status of the request (e.g., open, closed).     |

#### Comments Table
| Column Name    | Data Type  | Constraints                   | Description                                       |
| ---------------|------------|-------------------------------|---------------------------------------------------|
| id             | INT        | PRIMARY KEY, AUTO_INCREMENT   | Unique identifier for each request.              |
| comment_id       | VARCHAR(400) | NOT NULL                     | Unique identifier for the buyer making the request. |
| buyer_id          | VARCHAR(400) | NOT NULL                 | id of the buyer making the comment           |
| comment_title       | VARCHAR(255) |                             | Title of the comment .              |
| buyer_name     | VARCHAR(255)  | NOT NULL                     |  name of the buyer making the comment         |
| comment_place_id    | VARCHAR(255) | NOT NULL               | the id of the product or seller the comment was made about     |
| comment_date   | TIMESTAMP | NOT NULL               | date the comment was made     |

#### Favorites Table
| Column Name    | Data Type  | Constraints                   | Description                                       |
| ---------------|------------|-------------------------------|---------------------------------------------------|
| id             | INT        | PRIMARY KEY, AUTO_INCREMENT   | Unique identifier for each request.              |
| buyer_id       | VARCHAR(400) | NOT NULL                     | Unique identifier for the buyer that has the favorite |
| favorite_item_id | VARCHAR(400) | NOT NULL                 | id of the product or seller the buyer is adding to his favorites           |
| favorite_type       | VARCHAR(255) | NOT NULL               | whether the type is a seller or a product              |

#### Other Tables

- We would add more tables for other entities and relationships as needed.
