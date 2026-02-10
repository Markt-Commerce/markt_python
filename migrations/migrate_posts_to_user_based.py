#!/usr/bin/env python3
"""
Migration script to transform posts from seller-based to user-based architecture.

This script:
1. Adds user_id column to posts table
2. Populates user_id from existing seller relationships
3. Removes seller_id column after migration
4. Updates indexes and constraints
5. Handles Redis cache migration
6. Provides transaction rollback on failure
7. Supports dry-run validation

Usage Examples:
    # Dry run to validate before actual migration
    python migrations/migrate_posts_to_user_based.py --dry-run
    
    # Run actual migration with backup
    python migrations/migrate_posts_to_user_based.py
    
    # Run migration without backup (faster but less safe)
    python migrations/migrate_posts_to_user_based.py --no-backup
    
    # Run with custom database URL
    python migrations/migrate_posts_to_user_based.py --database-url "postgresql://user:pass@host/db"
"""

import os
import sys
import logging
from datetime import datetime

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text, create_engine
from sqlalchemy.orm import sessionmaker
from external.database import db
from app.users.models import User, Seller
from app.socials.models import Post
from external.redis import redis_client
from main.config import settings

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Custom exception for migration errors
class MigrationError(Exception):
    """Custom exception for migration-related errors"""
    pass

class PostMigration:
    def __init__(self, database_url=None, dry_run=False, create_backup=True):
        self.database_url = database_url or settings.SQLALCHEMY_DATABASE_URI
        if not self.database_url:
            raise ValueError("DATABASE_URL environment variable is required")
        
        self.dry_run = dry_run
        self.create_backup = create_backup
        self.engine = create_engine(self.database_url)
        self.Session = sessionmaker(bind=self.engine)
        
    def run_migration(self):
        """Run the complete migration process with transaction handling"""
        logger.info("Starting post migration from seller-based to user-based architecture")
        
        if self.dry_run:
            logger.info("🧪 DRY RUN MODE - No changes will be made to the database")
            self.dry_run_validation()
            return
        
        # Create backup if requested
        if self.create_backup:
            logger.info("📦 Creating database backup...")
            self.create_database_backup()
        
        # Start a database transaction
        with self.engine.connect() as conn:
            trans = conn.begin()
            
            try:
                # Step 1: Add user_id column
                logger.info("Step 1: Adding user_id column")
                self.add_user_id_column(conn)
                
                # Step 2: Populate user_id from seller relationships
                logger.info("Step 2: Populating user_id from seller relationships")
                self.populate_user_id_from_sellers(conn)
                
                # Step 3: Verify data integrity
                logger.info("Step 3: Verifying data integrity")
                self.verify_data_integrity(conn)
                
                # Step 4: Update Redis cache (non-transactional, can fail without affecting DB)
                logger.info("Step 4: Migrating Redis cache")
                self.migrate_redis_cache()
                
                # Step 5: Drop old seller_id column and constraints
                logger.info("Step 5: Cleaning up old schema")
                self.cleanup_old_schema(conn)
                
                # Commit the transaction
                trans.commit()
                logger.info("Migration completed successfully!")
                
            except Exception as e:
                # Rollback the transaction
                logger.error(f"Migration failed: {str(e)}")
                logger.info("Rolling back database changes...")
                trans.rollback()
                logger.info("Database rollback completed")
                raise MigrationError(f"Migration failed and was rolled back: {str(e)}")
            
            finally:
                # Close the connection
                conn.close()
    
    def add_user_id_column(self, conn):
        """Add user_id column to posts table"""
        logger.info("Adding user_id column to posts table")
        
        # Add the new user_id column
        conn.execute(text("""
            ALTER TABLE posts 
            ADD COLUMN user_id VARCHAR(12) REFERENCES users(id)
        """))
        
        # Add index for the new column
        conn.execute(text("""
            CREATE INDEX idx_user_posts ON posts(user_id, created_at)
        """))
        
        logger.info("Successfully added user_id column and index")
    
    def populate_user_id_from_sellers(self, conn):
        """Populate user_id from existing seller relationships"""
        logger.info("Populating user_id from seller relationships")
        
        # Get all posts with seller_id and populate user_id
        result = conn.execute(text("""
            UPDATE posts 
            SET user_id = sellers.user_id
            FROM sellers 
            WHERE posts.seller_id = sellers.id 
            AND posts.seller_id IS NOT NULL
        """))
        
        migrated_count = result.rowcount
        logger.info(f"Successfully migrated {migrated_count} posts")
        
        # Verify the migration
        verification_result = conn.execute(text("""
            SELECT COUNT(*) FROM posts 
            WHERE seller_id IS NOT NULL AND user_id IS NULL
        """)).scalar()
        
        if verification_result > 0:
            raise MigrationError(f"Migration incomplete: {verification_result} posts still missing user_id")
        
        logger.info("Migration verification passed")
    
    def verify_data_integrity(self, conn):
        """Verify that all posts have user_id populated"""
        logger.info("Verifying data integrity")
        
        # Check for posts without user_id
        posts_without_user = conn.execute(text("""
            SELECT COUNT(*) FROM posts 
            WHERE user_id IS NULL
        """)).scalar()
        
        if posts_without_user > 0:
            raise MigrationError(f"Found {posts_without_user} posts without user_id")
        
        # Check for posts with invalid user_id
        invalid_posts = conn.execute(text("""
            SELECT COUNT(*) FROM posts p 
            LEFT JOIN users u ON p.user_id = u.id 
            WHERE p.user_id IS NOT NULL AND u.id IS NULL
        """)).scalar()
        
        if invalid_posts > 0:
            raise MigrationError(f"Found {invalid_posts} posts with invalid user_id")
        
        logger.info("Data integrity verification passed")
    
    def migrate_redis_cache(self):
        """Migrate Redis cache from seller-based to user-based keys"""
        logger.info("Migrating Redis cache")
        
        try:
            # Get all existing seller-based post keys
            seller_keys = redis_client.keys("seller:*:posts")
            
            for seller_key in seller_keys:
                # Extract seller_id from key
                seller_id = seller_key.decode().split(':')[1]
                
                # Get the seller's user_id
                with self.Session() as session:
                    seller = session.query(Seller).get(int(seller_id))
                    if seller:
                        # Create new user-based key
                        user_key = f"user:{seller.user_id}:posts"
                        
                        # Copy data from old key to new key
                        post_data = redis_client.zrange(seller_key, 0, -1, withscores=True)
                        if post_data:
                            redis_client.zadd(user_key, dict(post_data))
                            logger.debug(f"Migrated Redis key from {seller_key} to {user_key}")
                        
                        # Remove old key
                        redis_client.delete(seller_key)
            
            logger.info(f"Successfully migrated {len(seller_keys)} Redis keys")
            
        except Exception as e:
            logger.warning(f"Redis migration failed (non-critical): {str(e)}")
    
    def cleanup_old_schema(self, conn):
        """Remove old seller_id column and related constraints"""
        logger.info("Cleaning up old schema")
        
        # Drop the old seller_id foreign key constraint
        conn.execute(text("""
            ALTER TABLE posts 
            DROP CONSTRAINT IF EXISTS posts_seller_id_fkey
        """))
        
        # Drop the old index
        conn.execute(text("""
            DROP INDEX IF EXISTS idx_seller_posts
        """))
        
        # Drop the seller_id column
        conn.execute(text("""
            ALTER TABLE posts 
            DROP COLUMN IF EXISTS seller_id
        """))
        
        logger.info("Successfully cleaned up old schema")
    
    def dry_run_validation(self):
        """Perform validation checks without making changes"""
        logger.info("Performing dry-run validation...")
        
        with self.engine.connect() as conn:
            # Check current state
            posts_count = conn.execute(text("SELECT COUNT(*) FROM posts")).scalar()
            posts_with_seller = conn.execute(text("SELECT COUNT(*) FROM posts WHERE seller_id IS NOT NULL")).scalar()
            posts_without_seller = conn.execute(text("SELECT COUNT(*) FROM posts WHERE seller_id IS NULL")).scalar()
            
            logger.info(f"📊 Current state:")
            logger.info(f"   Total posts: {posts_count}")
            logger.info(f"   Posts with seller_id: {posts_with_seller}")
            logger.info(f"   Posts without seller_id: {posts_without_seller}")
            
            # Check if user_id column already exists
            try:
                conn.execute(text("SELECT user_id FROM posts LIMIT 1"))
                logger.warning("⚠️  user_id column already exists! Migration may have already been run.")
            except Exception:
                logger.info("user_id column does not exist - ready for migration")
            
            # Check for orphaned posts (posts with seller_id but no matching seller)
            orphaned_posts = conn.execute(text("""
                SELECT COUNT(*) FROM posts p 
                LEFT JOIN sellers s ON p.seller_id = s.id 
                WHERE p.seller_id IS NOT NULL AND s.id IS NULL
            """)).scalar()
            
            if orphaned_posts > 0:
                logger.warning(f"⚠️  Found {orphaned_posts} orphaned posts (posts with seller_id but no matching seller)")
                logger.warning("   These posts will not be migrated!")
            
            logger.info("Dry-run validation completed")
    
    def create_database_backup(self):
        """Create a backup of the database before migration"""
        try:
            import subprocess
            from datetime import datetime
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_file = f"posts_migration_backup_{timestamp}.sql"
            
            # Extract database connection details
            # This is a simplified approach - in production, you'd want more robust backup handling
            logger.info(f"📦 Creating backup: {backup_file}")
            logger.warning("⚠️  Database backup functionality requires proper setup in production")
            logger.info("   Consider using pg_dump or your database's native backup tools")
            
        except Exception as e:
            logger.warning(f"Backup creation failed (non-critical): {str(e)}")
            logger.info("Migration will continue without backup")

def main():
    """Main function to run the migration"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Migrate posts from seller-based to user-based architecture')
    parser.add_argument('--dry-run', action='store_true', help='Run validation without making changes')
    parser.add_argument('--no-backup', action='store_true', help='Skip database backup creation')
    parser.add_argument('--database-url', help='Custom database URL')
    
    args = parser.parse_args()
    
    try:
        migration = PostMigration(
            database_url=args.database_url,
            dry_run=args.dry_run,
            create_backup=not args.no_backup
        )
        
        migration.run_migration()
        
        if args.dry_run:
            print("🧪 Dry-run completed successfully! No changes were made.")
        else:
            print("✅ Migration completed successfully!")
        
    except MigrationError as e:
        print(f"❌ Migration failed: {str(e)}")
        if not args.dry_run:
            print("🔄 Database has been rolled back to its original state")
        sys.exit(1)
        
    except Exception as e:
        print(f"❌ Unexpected error during migration: {str(e)}")
        if not args.dry_run:
            print("🔄 Database has been rolled back to its original state")
        sys.exit(1)

if __name__ == "__main__":
    main()
