"""review upvotes: one vote per user per review

Revision ID: c4fcdb10ec37
Revises: 4875f47262d6
Create Date: 2026-09-03 17:57:04.261565

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c4fcdb10ec37'
down_revision = '4875f47262d6'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "review_upvotes",
        sa.Column("user_id", sa.String(length=12), nullable=False),
        sa.Column("review_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["review_id"], ["product_reviews.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("user_id", "review_id"),
    )
    # The primary key covers (user_id, review_id), which does not serve the
    # count-by-review query. Index the other direction too.
    op.create_index(
        "ix_review_upvotes_review_id", "review_upvotes", ["review_id"]
    )

    # Backfill sellers.total_rating / total_raters.
    #
    # Nothing has ever written these columns, yet they are serialised into the
    # API, rendered on the shop profile, and used as the *default* sort for the
    # shop directory. Every seller currently reads 0.00 and "sort by rating"
    # orders by a column of zeros. Without this, the fix only applies to shops
    # that happen to receive a new review.
    op.execute(
        """
        UPDATE sellers AS s
        SET total_rating = COALESCE(agg.rating_sum, 0),
            total_raters = COALESCE(agg.rating_count, 0)
        FROM (
            SELECT p.seller_id,
                   SUM(r.rating)   AS rating_sum,
                   COUNT(r.rating) AS rating_count
            FROM product_reviews r
            JOIN products p ON p.id = r.product_id
            WHERE r.rating IS NOT NULL
            GROUP BY p.seller_id
        ) AS agg
        WHERE s.id = agg.seller_id
        """
    )
    # Sellers with no rated reviews at all: make the zero explicit rather than
    # leaving a NULL that the average calculation would have to guess at.
    op.execute(
        """
        UPDATE sellers
        SET total_rating = 0, total_raters = 0
        WHERE total_rating IS NULL OR total_raters IS NULL
        """
    )


def downgrade():
    op.drop_index("ix_review_upvotes_review_id", table_name="review_upvotes")
    op.drop_table("review_upvotes")
    # The seller aggregates are deliberately left populated. They are derived
    # values that were simply wrong before; zeroing them again on a rollback
    # would reintroduce the bug rather than undo a schema change.
