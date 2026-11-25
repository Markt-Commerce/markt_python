#!/usr/bin/env python
"""Close Mama Bisi's shared delivery run now, for the share-the-ride video.

Between the two takes of that video, a few hours have to pass in a few
seconds: the seller accepts the shared orders, the run closes and settles,
and each buyer's share -- cheaper than going alone -- is refunded to their
wallet. In production Celery beat closes runs at their cutoff; the demo stack
runs no beat, so this does it on demand:

  1. as Mama Bisi, accept every fulfilment request still waiting
  2. scripts/dev_make_orders_batchable.py --seller <hers> --close-now

    MARKT_DEMO=1 python scripts/demo_close_shared_run.py
"""

import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

API = os.environ.get("DEMO_API", "http://localhost:8000/api/v1")


def main() -> int:
    if os.environ.get("MARKT_DEMO") != "1":
        print("Refusing: set MARKT_DEMO=1 (local demo stack only).")
        return 2

    import seed_demo_stories as st

    requests, login, items = st._api(API)
    bisi = login(st._email(st.BISI), "seller")
    accepted = 0
    for a in items(
        requests.get(f"{API}/fulfilment/allocations", headers=bisi, timeout=30)
    ):
        if str(a.get("status", "")).lower() == "awaiting_seller":
            requests.post(
                f"{API}/fulfilment/allocations/{a['id']}/accept",
                headers=bisi,
                timeout=30,
            ).raise_for_status()
            accepted += 1
    print(f"Accepted {accepted} waiting request(s) as Mama Bisi.")

    from main.setup import create_flask_app

    with create_flask_app().app_context():
        from app.users.models import Seller

        seller_id = Seller.query.filter_by(user_id=st.BISI).one().id

    script = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "dev_make_orders_batchable.py"
    )
    out = subprocess.run(
        [
            sys.executable,
            script,
            "--seller",
            str(seller_id),
            "--close-now",
            "--allow-remote",
        ],
        capture_output=True,
        text=True,
    )
    print("\n".join(line for line in out.stdout.splitlines() if line.strip()))
    return out.returncode


if __name__ == "__main__":
    sys.exit(main())
