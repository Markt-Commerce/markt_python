import click
from flask import current_app
from flask.cli import with_appcontext
from external.database import db
from app.categories.models import Category
from app.categories.management.data import MAIN_CATEGORIES, SUBCATEGORIES


@click.command("populate-categories")
@click.option(
    "--force",
    is_flag=True,
    help="Force recreation of categories (will delete existing ones)",
)
@with_appcontext
def populate_categories(force):
    """Populate the categories table with standard ecommerce categories."""

    if force:
        click.echo("🗑️  Deleting existing categories...")
        Category.query.delete()
        db.session.commit()
        click.echo("✅ Existing categories deleted.")

    # Create main categories first
    created_categories = {}
    click.echo("📦 Creating main categories...")

    for cat_data in MAIN_CATEGORIES:
        category = Category(
            name=cat_data["name"],
            description=cat_data["description"],
            slug=cat_data["slug"],
            parent_id=cat_data["parent_id"],
            is_active=True,
        )
        db.session.add(category)
        db.session.flush()  # Get the ID
        created_categories[cat_data["name"]] = category.id
        click.echo(f"  ✅ Created: {cat_data['name']}")

    # Create subcategories
    click.echo("📦 Creating subcategories...")

    for subcat_data in SUBCATEGORIES:
        parent_id = created_categories.get(subcat_data["parent_name"])
        if parent_id:
            subcategory = Category(
                name=subcat_data["name"],
                description=subcat_data["description"],
                slug=subcat_data["slug"],
                parent_id=parent_id,
                is_active=True,
            )
            db.session.add(subcategory)
            click.echo(
                f"  ✅ Created: {subcat_data['name']} (under {subcat_data['parent_name']})"
            )

    # Commit all changes
    try:
        db.session.commit()
        click.echo(
            f"🎉 Successfully created {len(MAIN_CATEGORIES)} main categories and {len(SUBCATEGORIES)} subcategories!"
        )
        click.echo("📊 Category hierarchy is now ready for your ecommerce platform.")
    except Exception as e:
        db.session.rollback()
        click.echo(f"❌ Error creating categories: {str(e)}")
        raise
