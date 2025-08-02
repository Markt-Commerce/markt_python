import click
from flask import current_app
from flask.cli import with_appcontext
from app.categories.models import Category


@click.command("list-categories")
@with_appcontext
def list_categories():
    """List all categories in a hierarchical format."""

    categories = Category.query.filter_by(parent_id=None).all()

    if not categories:
        click.echo(
            "📭 No categories found. Run 'flask populate-categories' to create them."
        )
        return

    click.echo("📋 Categories Hierarchy:")
    click.echo("=" * 50)

    for category in categories:
        click.echo(f"📁 {category.name}")
        click.echo(f"   Description: {category.description}")
        click.echo(f"   Slug: {category.slug}")

        # Get subcategories
        subcategories = Category.query.filter_by(parent_id=category.id).all()
        if subcategories:
            click.echo("   📂 Subcategories:")
            for subcat in subcategories:
                click.echo(f"      • {subcat.name} ({subcat.slug})")
        else:
            click.echo("   📂 No subcategories")

        click.echo()
