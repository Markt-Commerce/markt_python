"""bring order_deliveries.state up to where the parcel actually got to

The rider flow never drove OrderDelivery.state. Dispatch set it as far as
JOB_CREATED and nothing advanced it after that, so the buyer's progress
list -- Paid, Rider requested, Rider assigned, Picked up, On the way,
Delivered -- froze at "Rider requested" for every order ever delivered.

The code fix only moves states forward from now on. Rows that are already
past are still wrong, and on a delivered order they stay wrong forever
because nothing will ever transition them again. This corrects them from
the facts recorded elsewhere: the assignment's logistical_status for
single orders, the run order's pod_status for batched ones, and the
order's own status as the backstop.

Only ever forwards, and only along the happy path. FAILED and CANCELLED
deliveries are left exactly as they are: those are endings somebody or
something decided deliberately, and a backfill inferring its way past one
would overwrite a real decision with a guess.

Revision ID: c8e41b73d92f
Revises: a3f6d20b8e14
Create Date: 2026-09-20
"""

from alembic import op


revision = "c8e41b73d92f"
down_revision = "a3f6d20b8e14"
branch_labels = None
depends_on = None


# How far along the happy path each state is. Used so the updates below
# can only ever move a row forward.
RANK = {
    "QUOTED": 0,
    "PAID": 1,
    "JOB_CREATED": 2,
    "ASSIGNED": 3,
    "PICKED_UP": 4,
    "IN_TRANSIT": 5,
    "DELIVERED": 6,
}

# Off-path states nothing here may touch.
TERMINAL = ("FAILED", "CANCELLED", "AWAITING_DISPATCH")


def _behind(target: str) -> str:
    """SQL fragment: rows on the happy path that are behind `target`."""
    ranked = [state for state, rank in RANK.items() if rank < RANK[target]]
    allowed = ", ".join(f"'{state}'" for state in ranked)
    terminal = ", ".join(f"'{state}'" for state in TERMINAL)
    return f"state::text IN ({allowed}) AND state::text NOT IN ({terminal})"


def upgrade():
    # A delivered order is delivered, whichever delivery model carried it
    # and whatever the intermediate rows say.
    op.execute(
        f"""
        UPDATE order_deliveries od
           SET state = 'DELIVERED', last_status_at = COALESCE(last_status_at, NOW())
          FROM orders o
         WHERE o.id = od.order_id
           AND o.status::text = 'DELIVERED'
           AND {_behind('DELIVERED')}
        """
    )

    # Single-order assignments still in flight.
    for logistical, target in (
        ("COMPLETED", "DELIVERED"),
        ("DELIVERED_PENDING_QR", "IN_TRANSIT"),
        ("EN_ROUTE_TO_DROPOFF", "IN_TRANSIT"),
        ("PICKED_UP", "PICKED_UP"),
        ("ARRIVED_PICKUP", "ASSIGNED"),
    ):
        op.execute(
            f"""
            UPDATE order_deliveries od
               SET state = '{target}',
                   last_status_at = COALESCE(last_status_at, NOW())
              FROM delivery_order_assignments a
             WHERE a.order_id = od.order_id
               AND a.status::text = 'ACCEPTED'
               AND a.logistical_status::text = '{logistical}'
               AND {_behind(target)}
            """
        )

    # Accepted but not yet started -- a rider exists, which is more than
    # "waiting for someone to take it".
    op.execute(
        f"""
        UPDATE order_deliveries od
           SET state = 'ASSIGNED', last_status_at = COALESCE(last_status_at, NOW())
          FROM delivery_order_assignments a
         WHERE a.order_id = od.order_id
           AND a.status::text = 'ACCEPTED'
           AND a.logistical_status IS NULL
           AND {_behind('ASSIGNED')}
        """
    )

    # Batched runs.
    for pod_status, target in (
        ("DELIVERED", "DELIVERED"),
        ("QR_ISSUED", "IN_TRANSIT"),
    ):
        op.execute(
            f"""
            UPDATE order_deliveries od
               SET state = '{target}',
                   last_status_at = COALESCE(last_status_at, NOW())
              FROM delivery_run_orders ro
             WHERE ro.order_id = od.order_id
               AND ro.pod_status::text = '{pod_status}'
               AND {_behind(target)}
            """
        )


def downgrade():
    # Deliberate no-op. The previous values were wrong -- they described a
    # delivery that had not happened yet for parcels already in someone's
    # hands -- and there is nothing recorded anywhere that says which of
    # them were stale, so putting them back is not something this can do
    # honestly.
    pass
