import click
from flask import current_app
from flask.cli import with_appcontext
from external.database import db
from app.categories.models import Category


@click.command("clear-categories")
@click.option("--confirm", is_flag=True, help="Confirm deletion without prompting")
@with_appcontext
def clear_categories(confirm):
    """Clear all categories from the database."""

    if not confirm:
        if not click.confirm("⚠️  Are you sure you want to delete ALL categories?"):
            click.echo("❌ Operation cancelled.")
            return

    try:
        count = Category.query.count()
        Category.query.delete()
        db.session.commit()
        click.echo(f"🗑️  Successfully deleted {count} categories.")
    except Exception as e:
        db.session.rollback()
        click.echo(f"❌ Error deleting categories: {str(e)}")
        raise
