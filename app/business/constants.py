"""Lookup values for Markt Business.

Kept as data here rather than as database enums so adding an industry, a
business type or a unit is a one-line change and never an ALTER TYPE. The
columns that hold them are plain strings; these lists are what the API
validates against and what the clients render as options (they are returned
by GET /business/config).
"""

BUSINESS_TYPES = [
    {"key": "producer", "label": "Producer"},
    {"key": "manufacturer", "label": "Manufacturer"},
    {"key": "supplier", "label": "Supplier"},
    {"key": "raw_material_supplier", "label": "Raw-material supplier"},
    {"key": "packaging_supplier", "label": "Packaging supplier"},
    {"key": "machinery_supplier", "label": "Machinery supplier"},
    {"key": "distributor", "label": "Distributor"},
    {"key": "wholesaler", "label": "Wholesaler"},
    {"key": "importer", "label": "Importer"},
    {"key": "exporter", "label": "Exporter"},
    {"key": "logistics_provider", "label": "Logistics provider"},
    {"key": "retail_business", "label": "Retail business"},
    {"key": "other", "label": "Other"},
]

INDUSTRIES = [
    {"key": "agriculture", "label": "Agriculture"},
    {"key": "food_processing", "label": "Food processing"},
    {"key": "beverages", "label": "Beverages"},
    {"key": "packaging", "label": "Packaging"},
    {"key": "pharmaceuticals", "label": "Pharmaceuticals"},
    {"key": "textiles", "label": "Textiles"},
    {"key": "construction", "label": "Construction"},
    {"key": "industrial", "label": "Industrial manufacturing"},
    {"key": "machinery", "label": "Machinery and equipment"},
    {"key": "chemicals", "label": "Chemicals"},
    {"key": "cosmetics", "label": "Cosmetics and personal care"},
    {"key": "logistics", "label": "Logistics"},
    {"key": "retail", "label": "Retail and wholesale"},
    {"key": "other", "label": "Other"},
]

UNITS = [
    {"key": "kg", "label": "Kilograms"},
    {"key": "tonne", "label": "Tonnes"},
    {"key": "g", "label": "Grams"},
    {"key": "litre", "label": "Litres"},
    {"key": "bag", "label": "Bags"},
    {"key": "piece", "label": "Pieces"},
    {"key": "carton", "label": "Cartons"},
    {"key": "crate", "label": "Crates"},
    {"key": "drum", "label": "Drums"},
    {"key": "bundle", "label": "Bundles"},
    {"key": "unit", "label": "Units"},
]

BUSINESS_TYPE_KEYS = {t["key"] for t in BUSINESS_TYPES}
INDUSTRY_KEYS = {i["key"] for i in INDUSTRIES}
UNIT_KEYS = {u["key"] for u in UNITS}

# The entitlement a subscription plan must carry for the is_business tag to
# count while subscriptions are on. Plans are configured by admins; this key
# is the only one the code itself knows about.
FEATURE_BUSINESS_ACCOUNT = "business_account"
