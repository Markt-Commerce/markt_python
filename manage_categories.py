#!/usr/bin/env python3
"""
Category Management Script

A simple wrapper script to run category management commands.
This script makes it easier to manage categories without remembering Flask CLI syntax.
"""

import os
import sys
import subprocess


def run_command(command):
    """Run a shell command and return the result."""
    try:
        result = subprocess.run(
            command, shell=True, check=True, capture_output=True, text=True
        )
        print(result.stdout)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error running command: {e}")
        print(f"Error output: {e.stderr}")
        return False


def main():
    """Main function to handle category management."""

    if len(sys.argv) < 2:
        print("Category Management Script")
        print("=" * 30)
        print("Usage:")
        print("  python manage_categories.py populate [--force]")
        print("  python manage_categories.py list")
        print("  python manage_categories.py clear [--confirm]")
        print("  python manage_categories.py help")
        return

    action = sys.argv[1].lower()

    # Set Flask app environment variable
    os.environ["FLASK_APP"] = "main.setup:create_flask_app"

    if action == "populate":
        force_flag = "--force" if "--force" in sys.argv else ""
        command = f"flask populate-categories {force_flag}".strip()
        print(f"Running: {command}")
        success = run_command(command)

        if success:
            print("\n✅ Categories populated successfully!")
            print("Run 'python manage_categories.py list' to see the categories.")
        else:
            print("\n❌ Failed to populate categories.")

    elif action == "list":
        command = "flask list-categories"
        print(f"Running: {command}")
        success = run_command(command)

        if not success:
            print("\n❌ Failed to list categories.")

    elif action == "clear":
        confirm_flag = "--confirm" if "--confirm" in sys.argv else ""
        command = f"flask clear-categories {confirm_flag}".strip()
        print(f"Running: {command}")
        success = run_command(command)

        if success:
            print("\n✅ Categories cleared successfully!")
        else:
            print("\n❌ Failed to clear categories.")

    elif action == "help":
        print("Category Management Commands")
        print("=" * 30)
        print()
        print(
            "populate [--force]  - Populate database with standard ecommerce categories"
        )
        print("                    Use --force to recreate existing categories")
        print()
        print("list               - Display all categories in hierarchical format")
        print()
        print("clear [--confirm]  - Remove all categories from database")
        print("                    Use --confirm to skip confirmation prompt")
        print()
        print("help               - Show this help message")
        print()
        print("Examples:")
        print("  python manage_categories.py populate")
        print("  python manage_categories.py populate --force")
        print("  python manage_categories.py list")
        print("  python manage_categories.py clear --confirm")

    else:
        print(f"Unknown action: {action}")
        print("Run 'python manage_categories.py help' for usage information.")


if __name__ == "__main__":
    main()
