"""HTTP smoke test for the feed, wallet and account-deletion work.

Drives the running local API with real requests. Everything here exercises a
real request path -- nothing is mocked -- so it catches the class of bug the
unit suite structurally cannot: routing, serialization, auth wiring, signature
verification over a genuinely raw body, and ledger behaviour under replay.

    PYTHONPATH=. python tests/smoke/smoke_api.py

Needs the server running against a seeded disposable database -- see
tests/smoke/reset_smoke_env.sh. The account-deletion section exercises
endpoints that live on feature/account-deletion, so a full green run needs
both that branch and feature/wallet-audit present.

Refuses to run against a non-local API or with a Paystack live key.
"""

import hashlib
import hmac
import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("SMOKE_API_BASE", "http://127.0.0.1:8010/api/v1")
PASSWORD = "SmokeTest!2026"

SELLER_A = "smoke.seller.a@markt-smoke.example.com"
BUYER_A = "smoke.buyer.a@markt-smoke.example.com"
BUYER_B = "smoke.buyer.b@markt-smoke.example.com"
DISPOSABLE = "smoke.disposable@markt-smoke.example.com"

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return ok


def section(title):
    print(f"\n{title}\n{'-' * len(title)}")


def call(method, path, token=None, body=None, raw=None, headers=None):
    """Returns (status, parsed_or_text). Never raises on HTTP error status."""
    url = path if path.startswith("http") else f"{BASE}{path}"
    data = (
        raw
        if raw is not None
        else (json.dumps(body).encode() if body is not None else None)
    )
    hdrs = {"Accept": "application/json"}
    if data is not None:
        hdrs["Content-Type"] = "application/json"
    if token:
        hdrs["Authorization"] = f"Bearer {token}"
    hdrs.update(headers or {})

    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            text = resp.read().decode()
            status = resp.status
    except urllib.error.HTTPError as e:
        text = e.read().decode()
        status = e.code
    except Exception as e:  # connection refused etc
        return 0, str(e)
    try:
        return status, json.loads(text) if text else None
    except json.JSONDecodeError:
        return status, text


def unwrap(payload):
    if isinstance(payload, dict) and "data" in payload and payload["data"] is not None:
        return payload["data"]
    return payload


def login(email, account_type):
    status, body = call(
        "POST",
        "/users/login",
        body={"email": email, "password": PASSWORD, "account_type": account_type},
    )
    if status != 200:
        return None, None
    b = unwrap(body)
    return b.get("access_token"), b.get("id")


# --------------------------------------------------------------------------
def guard():
    section("Safety preconditions")
    from main.config import settings

    local = any(h in BASE for h in ("127.0.0.1", "localhost"))
    if not check("API base is local", local, BASE):
        sys.exit(1)
    if not check(
        "DB is a *_smoke database",
        settings.DB_NAME.endswith("_smoke"),
        settings.DB_NAME,
    ):
        sys.exit(1)
    if not check(
        "DB host is local",
        settings.DB_HOST in ("127.0.0.1", "localhost"),
        settings.DB_HOST,
    ):
        sys.exit(1)
    secret = settings.PAYSTACK_SECRET_KEY or ""
    if not check(
        "Paystack key is TEST mode", secret.startswith("sk_test_"), secret[:8]
    ):
        sys.exit(1)
    return secret


def sign(secret, raw):
    """Exactly what the handler verifies: HMAC-SHA512 over the raw body."""
    return hmac.new(secret.encode(), raw, hashlib.sha512).hexdigest()


def post_webhook(secret, event, data, tamper=False):
    payload = {"event": event, "data": data}
    raw = json.dumps(payload).encode()
    sig = sign(secret, raw)
    if tamper:
        sig = sig[:-1] + ("0" if sig[-1] != "0" else "1")
    return call(
        "POST",
        "/payments/webhook/paystack",
        raw=raw,
        headers={"X-Paystack-Signature": sig},
    )


def get_balance(token):
    status, body = call("GET", "/wallet/", token=token)
    if status != 200:
        return None
    return unwrap(body).get("available_balance")


# --------------------------------------------------------------------------
def main():
    secret = guard()

    section("Auth")
    seller_token, seller_id = login(SELLER_A, "seller")
    buyer_token, buyer_id = login(BUYER_A, "buyer")
    buyer_b_token, _ = login(BUYER_B, "buyer")
    check("seller_a login returns bearer token", bool(seller_token))
    check("buyer_a login returns bearer token", bool(buyer_token))
    check("buyer_b login returns bearer token", bool(buyer_b_token))

    status, _ = call("GET", "/wallet/")
    check(
        "unauthenticated wallet read is rejected",
        status in (401, 403),
        f"status {status}",
    )

    status, body = call("GET", "/users/profile", token=seller_token)
    check(
        "bearer token authenticates /users/profile", status == 200, f"status {status}"
    )

    # ---------------------------------------------------------------- feed
    section("Feed")
    status, body = call("GET", "/socials/feed?page=1&per_page=10", token=buyer_token)
    feed = unwrap(body) if status == 200 else {}
    items = feed.get("items", []) if isinstance(feed, dict) else []
    check("GET /socials/feed returns 200", status == 200, f"status {status}")
    check("feed returns items", len(items) > 0, f"{len(items)} items")

    kinds = {i.get("type") for i in items}
    check(
        "feed is mixed (posts and products)",
        {"post", "product"} <= kinds,
        f"types={sorted(kinds)}",
    )

    pag = feed.get("pagination", {}) if isinstance(feed, dict) else {}
    check(
        "feed exposes pagination the app relies on",
        all(k in pag for k in ("page", "per_page", "has_next")),
        str(sorted(pag))[:120],
    )

    ids = [i.get("id") for i in items]
    check(
        "feed item ids are unique and present",
        len(ids) == len(set(ids)) and all(ids),
        f"{len(ids)} ids",
    )

    post = next((i for i in items if i.get("type") == "post"), None)
    product = next((i for i in items if i.get("type") == "product"), None)

    if post:
        before = post.get("likes_count", 0)
        status, _ = call("POST", f"/socials/posts/{post['id']}/like", token=buyer_token)
        check("like a feed post", status in (200, 201), f"status {status}")
        # NB: the detail endpoint names these like_count/comment_count while the
        # feed uses likes_count/comments_count. Read both rather than assuming.
        status, detail = call("GET", f"/socials/posts/{post['id']}", token=buyer_token)
        d = unwrap(detail) if status == 200 else {}
        after = d.get("like_count", d.get("likes_count"))
        check(
            "like persists (count incremented)",
            after == before + 1,
            f"{before} -> {after}",
        )
        check(
            "post detail returns liked_by_me for the liker",
            d.get("liked_by_me") is True,
            f"liked_by_me={d.get('liked_by_me')}",
        )

        status, _ = call(
            "POST",
            f"/socials/posts/{post['id']}/comments",
            token=buyer_token,
            body={"content": "smoke-fixture: nice one"},
        )
        check("comment on a feed post", status in (200, 201), f"status {status}")
        status, detail = call("GET", f"/socials/posts/{post['id']}", token=buyer_token)
        d2 = unwrap(detail) if status == 200 else {}
        cc = d2.get("comment_count", d2.get("comments_count"))
        check(
            "comment persists (count incremented)",
            (cc or 0) >= 1,
            f"comment_count={cc}",
        )
    else:
        check("post flows exercised", False, "no post in feed")

    if product:
        seller_ref = (product.get("seller") or {}).get("id")
        check(
            "product carries seller.id for the shop tap",
            seller_ref is not None,
            f"seller.id={seller_ref}",
        )
        if seller_ref is not None:
            status, _ = call("GET", f"/users/shops/{seller_ref}", token=buyer_token)
            check("shop tap destination resolves", status == 200, f"status {status}")

        status, _ = call("POST", f"/products/{product['id']}/view", token=buyer_token)
        check("product view tracking accepts", status in (200, 204), f"status {status}")

        status, _ = call(
            "POST",
            "/cart/add",
            token=buyer_token,
            body={"product_id": product["id"], "quantity": 1, "variant_id": 0},
        )
        added = status in (200, 201)
        check("add feed product to cart", added, f"status {status}")
        status, cart = call("GET", "/cart/", token=buyer_token)
        check("cart read back after add", status == 200, f"status {status}")

        followee = ((product.get("seller") or {}).get("user") or {}).get("id")
        if followee:
            status, _ = call("POST", f"/socials/follow/{followee}", token=buyer_token)
            check("follow seller from feed", status in (200, 201), f"status {status}")
    else:
        check("product flows exercised", False, "no product in feed")

    # -------------------------------------------------------------- wallet
    section("Wallet — top-up, callback, webhook")
    start_balance = get_balance(seller_token)
    check(
        "wallet balance readable", start_balance is not None, f"balance={start_balance}"
    )

    status, body = call(
        "POST",
        "/wallet/topup/initialize",
        token=seller_token,
        body={"amount": 5000, "currency": "NGN", "platform": "mobile"},
    )
    init = unwrap(body) if status in (200, 201) else {}
    topup_id = init.get("topup_id")
    reference = init.get("reference")
    check("top-up initialize returns 201", status in (200, 201), f"status {status}")
    check("top-up returns an authorization_url", bool(init.get("authorization_url")))
    check("top-up returns a reference", bool(reference), f"ref={reference}")

    # (a) the route that used to 404
    status, _ = call("GET", f"/wallet/topup/callback/{topup_id}?platform=mobile")
    check(
        "top-up callback route resolves (was 404)",
        status in (200, 302),
        f"status {status}",
    )

    raw_status, location = 0, ""
    try:
        req = urllib.request.Request(
            f"{BASE}/wallet/topup/callback/{topup_id}?platform=mobile", method="GET"
        )

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **kw):
                return None

        opener = urllib.request.build_opener(NoRedirect)
        try:
            opener.open(req)
        except urllib.error.HTTPError as e:
            raw_status, location = e.code, e.headers.get("Location", "")
    except Exception as e:
        location = f"error: {e}"
    check(
        "callback redirects to the mobile deep link",
        location.startswith("markt://wallet/"),
        location[:80],
    )

    status, body = call("GET", f"/wallet/topup/{topup_id}/verify", token=seller_token)
    v = unwrap(body) if status == 200 else {}
    check("verify endpoint responds", status == 200, f"status {status}")
    check(
        "unpaid top-up is not credited",
        v.get("verified") is False,
        f"verified={v.get('verified')}",
    )
    check(
        "balance unchanged by an unpaid top-up",
        get_balance(seller_token) == start_balance,
        f"{start_balance} -> {get_balance(seller_token)}",
    )

    # (b) signed webhook credits exactly once
    section("Wallet — webhook signature, credit, idempotency")
    status, _ = post_webhook(
        secret,
        "charge.success",
        {
            "reference": reference,
            "status": "success",
            "amount": 500000,
            "currency": "NGN",
        },
        tamper=True,
    )
    check("tampered signature is rejected", status == 400, f"status {status}")
    check(
        "balance unchanged after tampered webhook",
        get_balance(seller_token) == start_balance,
        f"balance={get_balance(seller_token)}",
    )

    status, _ = post_webhook(
        secret,
        "charge.success",
        {
            "reference": reference,
            "status": "success",
            "amount": 500000,
            "currency": "NGN",
        },
    )
    after_credit = get_balance(seller_token)
    check("validly signed webhook accepted", status == 200, f"status {status}")
    check(
        "balance moved by exactly the reported amount",
        after_credit == round((start_balance or 0) + 5000, 2),
        f"{start_balance} -> {after_credit} (expected +5000)",
    )

    # (c) replay
    for i in range(5):
        post_webhook(
            secret,
            "charge.success",
            {
                "reference": reference,
                "status": "success",
                "amount": 500000,
                "currency": "NGN",
            },
        )
    replayed = get_balance(seller_token)
    check(
        "5x replay does not move the balance again",
        replayed == after_credit,
        f"{after_credit} -> {replayed}",
    )

    status, body = call(
        "GET", "/wallet/transactions?page=1&per_page=50", token=seller_token
    )
    txs = unwrap(body).get("transactions", []) if status == 200 else []
    topup_rows = [t for t in txs if t.get("reference_type") == "wallet_topup"]
    check(
        "exactly one ledger row for the top-up after replay",
        len(topup_rows) == 1,
        f"{len(topup_rows)} rows",
    )
    check(
        "ledger balance_after agrees with balance endpoint",
        txs and txs[0].get("balance_after") == replayed,
        f"ledger={txs[0].get('balance_after') if txs else None} api={replayed}",
    )

    # (d) payload verification
    section("Wallet — payload verification")
    for label, data in [
        ("wrong amount", {"status": "success", "amount": 999999, "currency": "NGN"}),
        ("wrong currency", {"status": "success", "amount": 300000, "currency": "USD"}),
        ("failed status", {"status": "failed", "amount": 300000, "currency": "NGN"}),
    ]:
        st2, b2 = call(
            "POST",
            "/wallet/topup/initialize",
            token=seller_token,
            body={"amount": 3000, "currency": "NGN", "platform": "mobile"},
        )
        ref2 = unwrap(b2).get("reference") if st2 in (200, 201) else None
        pre = get_balance(seller_token)
        data = dict(data, reference=ref2)
        post_webhook(secret, "charge.success", data)
        post = get_balance(seller_token)
        check(
            f"signed webhook with {label} does not credit",
            pre == post,
            f"{pre} -> {post}",
        )

    # (f) consistency
    section("Wallet — read-back consistency")
    bal = get_balance(seller_token)
    status, body = call(
        "GET", "/wallet/transactions?page=1&per_page=100", token=seller_token
    )
    txs = unwrap(body).get("transactions", []) if status == 200 else []
    computed = 0.0
    for t in sorted(txs, key=lambda r: r["id"]):
        computed += t["amount"] if t["type"] == "credit" else -t["amount"]
    check(
        "ledger sums to the reported balance",
        round(computed, 2) == round(bal, 2),
        f"sum={round(computed,2)} balance={bal}",
    )

    status, body = call(
        "GET", "/wallet/withdrawals?page=1&per_page=20", token=seller_token
    )
    check("withdrawal list endpoint responds", status == 200, f"status {status}")

    # ------------------------------------------------------- deletion
    section("Account deletion")
    dis_token, dis_id = login(DISPOSABLE, "buyer")
    check("disposable user logs in", bool(dis_token), dis_id or "")

    status, body = call("GET", "/users/account/deletion-check", token=dis_token)
    dc = unwrap(body) if status == 200 else {}
    check("deletion-check responds", status == 200, f"status {status}")
    check(
        "clean account reports can_delete", dc.get("can_delete") is True, str(dc)[:120]
    )

    status, _ = call(
        "DELETE",
        "/users/account",
        token=dis_token,
        body={"password": "wrong-password", "confirmation": "DELETE"},
    )
    check("wrong password is rejected", status in (401, 403), f"status {status}")

    status, _ = call(
        "DELETE",
        "/users/account",
        token=dis_token,
        body={"password": PASSWORD, "confirmation": "NOPE"},
    )
    check(
        "bad confirmation string is rejected", status in (400, 422), f"status {status}"
    )

    status, body = call(
        "DELETE",
        "/users/account",
        token=dis_token,
        body={"password": PASSWORD, "confirmation": "DELETE"},
    )
    check("account deletion succeeds", status == 200, f"status {status}")

    status, _ = call("GET", "/users/profile", token=dis_token)
    check(
        "pre-deletion bearer token no longer authenticates",
        status in (401, 403),
        f"status {status}",
    )

    tok2, _ = login(DISPOSABLE, "buyer")
    check("deleted account cannot log in again", tok2 is None)

    # An account with an order in flight: real checkout, then re-check.
    # buyer_b is used so the earlier cart work on buyer_a can't interfere.
    status, _ = call(
        "POST",
        "/cart/add",
        token=buyer_b_token,
        body={"product_id": product["id"], "quantity": 1, "variant_id": 0},
    )
    addr = {
        "recipient_name": "Smoke Buyer B",
        "street_address": "1 Smoke Lane",
        "city": "Lagos",
        "state": "Lagos",
        "postal_code": "100001",
        "country": "Nigeria",
        "phone_number": "+2348000000000",
    }
    status, body = call(
        "POST",
        "/cart/checkout",
        token=buyer_b_token,
        body={"shipping_address": addr, "billing_address": addr},
    )
    order_created = status in (200, 201)
    check(
        "checkout creates an order (for the blocker test)",
        order_created,
        f"status {status}",
    )

    if order_created:
        status, body = call("GET", "/users/account/deletion-check", token=buyer_b_token)
        dc3 = unwrap(body) if status == 200 else {}
        codes3 = [b.get("code") for b in dc3.get("blockers", [])]
        check(
            "account with an order in flight reports an open-order blocker",
            dc3.get("can_delete") is False and "open_orders_buying" in codes3,
            str(codes3),
        )
        status, _ = call(
            "DELETE",
            "/users/account",
            token=buyer_b_token,
            body={"password": PASSWORD, "confirmation": "DELETE"},
        )
        check(
            "deletion is refused while an order is in flight",
            status == 409,
            f"status {status}",
        )

    # blocked deletion: seller_a has a wallet balance
    status, body = call("GET", "/users/account/deletion-check", token=seller_token)
    dc2 = unwrap(body) if status == 200 else {}
    codes = [b.get("code") for b in dc2.get("blockers", [])]
    check(
        "funded account reports a wallet blocker",
        dc2.get("can_delete") is False and "wallet_balance" in codes,
        str(codes),
    )

    status, body = call(
        "DELETE",
        "/users/account",
        token=seller_token,
        body={"password": PASSWORD, "confirmation": "DELETE"},
    )
    check(
        "deletion of a funded account is refused with 409",
        status == 409,
        f"status {status}",
    )
    status, _ = call("GET", "/users/profile", token=seller_token)
    check(
        "refused deletion leaves the account usable", status == 200, f"status {status}"
    )

    # ------------------------------------------------------------- report
    section("Summary")
    passed = sum(1 for _, ok, _ in results if ok)
    failed = [(n, d) for n, ok, d in results if not ok]
    print(f"  {passed}/{len(results)} checks passed")
    if failed:
        print("  Failures:")
        for n, d in failed:
            print(f"    - {n} ({d})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
