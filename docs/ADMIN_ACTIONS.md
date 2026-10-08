# Markt Admin — Actions Catalog

Working catalog of every admin capability we can build, derived from a sweep of
the backend (`markt_python`) domain models/services and the client apps
(`markt_mobile` buyer/seller app, `markt_logistics` rider app, `markt-web`
marketing site). Build order: **backend first, then the web admin app**. No
admin mobile surface for now.

Legend for status:
- ✅ **Exists** — endpoint/service already implemented, admin-gated.
- 🟡 **Partial** — logic exists (model/service) but no admin endpoint, or gated by a `TODO`.
- 🔨 **To build** — new admin capability.

---

## 0. Admin platform foundations (build these first)

The bones already exist but are thin — harden before layering features on top.

- ✅ `User.is_admin` boolean flag (`app/users/models.py`).
- ✅ `admin_required` decorator + `require_permission(...)` / `_has_permission`
  in `app/libs/decorators.py`.
- 🟡 `_has_permission` is a stub (`permission_map` hardcoded, comment says "in a
  real system you'd have a proper permission system").

**To build:**
- 🔨 **Proper RBAC / roles for staff** — admin roles (e.g. super-admin, support,
  finance, moderation, logistics-ops) instead of a single `is_admin` bool, backed
  by a real permission map. Every action below should map to a named permission.
- 🔨 **Admin audit log** — immutable record of who did what (actor, action,
  target, before/after, reason, timestamp). Nearly every action below is
  irreversible or money/trust-sensitive and must be auditable.
- 🔨 **Admin authentication** — separate admin login / session, ideally with
  enforced 2FA for staff accounts.
- 🔨 **Admin dashboard shell** (web) — nav, search-anything, role-scoped menus.

---

## 1. User & account management

Backing: `app/users/models.py` (`User`, `Buyer`, `Seller`, `SocialAccount`,
`UserSettings`, `UserAddress`), `SellerVerificationStatus`
(`unverified`/`pending`/`verified`/`suspended`), `MarketVerificationStatus`
(`unverified`/`verified`/`flagged`).

- 🔨 **Search / list / view users** — by email, name, id, role, status; see
  profile, buyer & seller sub-profiles, addresses, activity.
- 🔨 **Suspend / reinstate a user account** — block login (mirror the
  `SUSPENDED` pattern used for delivery users).
- 🔨 **Ban / delete (soft) a user**.
- 🔨 **Force email verification / resend verification** (`email_verified` flag,
  `send_email_verification` service exists for self-serve).
- 🔨 **Reset a user's password / force logout** (revoke sessions/tokens — see
  `app/libs/auth_tokens.py`).
- 🔨 **Edit user profile fields** (support corrections).
- 🔨 **Impersonate / "view as user"** (support debugging — gated + audited).
- 🔨 **Manage a user's roles** (buyer/seller enablement, `current_role`).

## 2. Seller verification & shop management

Backing: `Seller.verification_status`, `market_verification_status`, payout bank
fields, `Seller` in `app/users/models.py`. **No admin approval endpoint exists
today — this is a core gap.**

- 🔨 **Seller verification queue** — list sellers in `pending`, review submitted
  docs/details.
- 🔨 **Approve seller verification** → `verified`.
- 🔨 **Reject seller verification** (with reason) → back to `unverified`.
- 🔨 **Suspend / un-suspend a seller** → `suspended` (blocks selling).
- 🔨 **Review market-verification flags** — sellers whose geocoded shop address
  is outside market tolerance are `flagged` and excluded from rerouting;
  admin confirms/overrides (`MarketVerificationStatus.FLAGGED`).
- 🔨 **Edit / verify seller payout bank details** (`payout_bank_code`,
  `payout_account_number`, `payout_account_name`).
- 🔨 **Feature / unfeature a shop** (banner, promotion).

## 3. Products & inventory

Backing: `app/products/models.py` `ProductStatus`
(`active`/`draft`/`archived`/`out_of_stock`/`deleted`), `app/inventory/models.py`
(`InventoryReservation`, `ProductHandling`/`HandlingClass`,
`InventoryConfidenceScore`, `CategoryConfidencePrior`).

- 🔨 **List / search all products** across sellers with status filters.
- 🔨 **Takedown / archive / restore a product** (set `ProductStatus`, incl.
  soft `deleted`).
- 🔨 **Force a product `out_of_stock`** / correct inventory.
- 🔨 **Edit product handling class** (`HandlingClass` — e.g. PERISHABLE affects
  delivery failure handling).
- 🔨 **Review/adjust inventory confidence scores & category priors** (ops tuning).
- 🔨 **Inspect inventory reservations** (stuck/expired holds).

## 4. Categories, tags, markets & niches (catalog config)

Backing: `app/categories/` (`Category`, `Product/Post/Request/Seller/Niche
Category`, `Tag`; CLI in `manage_categories.py` + `app/categories/management/`),
`app/markets/models.py` (`Market`, `Area`), `app/socials` niches.

- 🟡 **Create / update category & tag** — endpoints exist but marked
  `# TODO: Add admin check` (`app/categories/routes.py`). **Gate them.**
- 🔨 **Full category tree CRUD** via admin UI (currently CLI-only).
- 🔨 **Manage tags** (merge, rename, delete).
- 🔨 **Manage markets & areas** (`Market`, `Area`) — create/edit coverage areas.
- 🔨 **Manage niches** — see moderation (§7) for niche moderation actions.

## 5. Orders, fulfilment & disputes

Backing: `app/orders/models.py` `OrderStatus`
(`pending_payment`/`processing`/`ready_for_delivery`/`shipped`/`delivered`/
`cancelled`/`returned`/`failed`), `OrderReturn` + `OrderReturnStatus`
(`.../refunded`), `Shipment`; `app/fulfilment/models.py`
`FulfilmentAllocationStatus` (awaiting_seller, awaiting_buyer_approval,
buyer_rejected, rerouting, timeout, ...).

- 🔨 **List / search / view any order** (buyer, seller, items, timeline, payment).
- 🔨 **Manually change order status** (`OrderStatus`) — unstick or correct
  orders; respect valid transitions.
- 🔨 **Cancel an order** on behalf of a party (`cancel_reason`).
- 🔨 **Resolve order returns** (`OrderReturn` → `refunded`/rejected, set
  `refund_amount`).
- 🔨 **Dispute resolution workspace** — buyer-vs-seller disputes (non-delivery,
  item-not-as-described): decide outcome, trigger refund/settlement, add notes.
- 🔨 **Inspect / intervene in fulfilment allocations** — clear `rerouting`,
  `timeout`, and other stuck states surfaced by metrics `stuck_orders`.
- 🔨 **Override substitution / buyer-approval flows** when a party is unresponsive.

## 6. Payments, wallets & payouts (finance ops)

Backing: `app/payments/models.py` (`Payment`/`PaymentStatus`
`.../refunded`/`partially_refunded`, `Transaction`), `app/wallet/models.py`
(`WalletAccount` for both users **and** delivery users, `WalletEntry`,
`WithdrawalRequest`/`WithdrawalStatus` pending→processing→completed/failed,
`WalletTopUp`/`TopUpStatus`). Services: `settle_order_item`,
`credit_delivery_earning`, `refund_order(_item)_to_wallet`, `request_withdrawal`.

- ✅ **Payment stats** (`/payments/admin/stats`) — *note: currently gated
  `seller_required`, likely should be admin.*
- 🔨 **View any payment / transaction**; reconcile against gateway.
- 🔨 **Issue a refund** — full or partial → `refunded`/`partially_refunded`,
  route to wallet via existing refund services.
- 🔨 **Withdrawal / payout queue** — `WithdrawalRequest` has no admin
  processing endpoint today. Admin needs to **approve → mark processing →
  completed / failed** (with `failure_reason`) for seller & rider payouts.
- 🔨 **View any wallet** (user or delivery partner) — balance, ledger entries.
- 🔨 **Manual wallet credit / debit / adjustment** (goodwill, correction,
  clawback) — audited, with reason (`WalletEntry` + `WalletReferenceType`).
- 🔨 **Force-settle an order item** to seller/rider (`settle_order_item`).
- 🔨 **Review failed top-ups & withdrawals**.

## 7. Moderation & trust/safety

Backing: `app/moderation/models.py` (`ContentReport`, `ReportStatus`
pending/reviewing/actioned/dismissed, `ReportReason`, `ReportedContentType`
post/product/comment/chat_message/user, `UserBlock`); `app/socials/models.py`
(`Post`/`PostStatus`, `NichePost`, `ProductReview`, `NicheModerationAction`,
`Niche`/`NicheStatus`/`NicheVisibility`).

- ✅ **Resolve a content report** (`/moderation/... resolve`, `admin_required`,
  `ReportResolveSchema`) → actioned/dismissed with `resolution_note`.
- 🔨 **Moderation queue UI** — filter reports by type/reason/status, bulk triage,
  claim (`reviewing`), assign reviewer (`reviewed_by`).
- 🔨 **Take content down** off a report — hide/remove post, product, comment,
  chat message, review (`PostStatus`, product takedown links to §3).
- 🔨 **Act on reported user** — warn / suspend / ban from a report.
- 🔨 **Manage niches** — `NicheStatus`/visibility, ban/warn/remove within a niche
  (`NicheModerationAction` action_types: ban, warn, remove_post…); review
  member-moderator actions.
- 🔨 **Moderate product reviews** (`ProductReview`, `ReviewUpvote`) — remove
  fake/abusive reviews.
- 🔨 **View user block graph** (`UserBlock`) for abuse investigations.

## 8. Deliveries & logistics ops

Backing: `app/deliveries/models.py` — `DeliveryUser`/`DeliveryStatus`
(active/inactive/**suspended**), `DeliveryVehicleType`, `DeliveryRun` +
`DeliveryRunStatus` (open→cutoff→planning→rider_assignment→…→completed/
partially_completed/cancelled, with `VALID_STATUS_TRANSITIONS`),
`DeliveryOrderAssignment`/`AssignmentStatus`, `DeliveryRunStop`, PoD statuses,
and `DeliveryFailure` (`DeliveryFailureReason`, `DeliveryRecoveryAction`,
`DeliveryCostBearer`, `DeliveryFailureOutcome` pending→resolved).

- ✅ **Assign a rider to a run** (admin-only, `app/deliveries/routes.py`).
- ✅ **Confirm/mark a run action carried out** (admin-only).
- ✅ **Resolve a delivery failure** (`admin_required`) — set recovery action &
  cost bearer.
- ✅ **Complete a delivery failure** (`admin_required`).
- 🔨 **Delivery-partner (rider) verification & onboarding review** — approve
  rider, set/verify `vehicle_type`.
- 🔨 **Suspend / reinstate a delivery partner** (`DeliveryStatus.SUSPENDED`).
- 🔨 **Live runs board** — view/monitor runs, force status transitions, cancel a
  run (`cancel_reason`), manually advance stuck runs.
- 🔨 **Reassign / reject rider assignments** (`AssignmentStatus`).
- 🔨 **Failure/exception queue** — perishable/urgent flags, decide
  refund-buyer vs seller/Markt bears cost (`DeliveryCostBearer`), dispose/return.
- 🔨 **View rider live location / last location** for support
  (`DeliveryLastLocation`, `OrderLocationMapping`).

## 9. Delivery pricing config (logistics finance)

Backing: `app/delivery_pricing/models.py` (`ServiceCity`, `ServiceZone`,
`DeliveryLane`, `DeliveryQuote`/`QuoteStatus`).

- 🔨 **Manage service cities & zones** (coverage on/off, boundaries).
- 🔨 **Manage delivery lanes & pricing** (`DeliveryLane` rates).
- 🔨 **Inspect / expire delivery quotes** (`DeliveryQuote`).

## 10. Requests marketplace (buyer requests ↔ seller offers)

Backing: `app/requests/models.py` (`BuyerRequest`/`RequestStatus`,
`SellerOffer`/`OfferStatus`, `RequestSource`).

- 🔨 **List / moderate buyer requests** — remove spam/abusive requests.
- 🔨 **Moderate seller offers**; intervene in disputed request fulfilment.

## 11. Gamification & rewards

Backing: `app/gamification/models.py` (`PointsLedger`, `UserStats`,
`SellerStats`, `Badge`, `UserBadge`, `TierConfig`, `LeaderboardSnapshot`).

- 🔨 **Create / edit badges** (`Badge`) and award/revoke badges (`UserBadge`).
- 🔨 **Configure tiers** (`TierConfig`) — thresholds, perks.
- 🔨 **Adjust points** (`PointsLedger`) — corrections, anti-abuse clawbacks.
- 🔨 **Review leaderboards** (`LeaderboardSnapshot`) and correct anomalies.

## 12. Notifications & comms

Backing: `app/notifications/models.py` (`Notification`/`NotificationType`,
`PushToken`), realtime sockets (`app/realtime`, `main/sockets.py`).

- 🔨 **Send broadcast / targeted notifications** (announcements, incidents).
- 🔨 **Manage notification templates / types**.
- 🔨 **Inspect a user's notifications & push tokens** for support.

## 13. Metrics, health & platform ops

Backing: `app/metrics/` (fulfilment latency, rerouting, reservation/payment
failure rates, substitution rate, missed seller windows, **stuck orders**,
worker failures — `MetricsDashboard` is `admin_required`), `app/media/`
(`MediaStats` admin-only), `app/health/`, `app/ops/tasks.py`,
`main/schedules.py`, `main/workers.py`.

- ✅ **Metrics dashboard** (`/metrics`, admin-only).
- ✅ **Media statistics** (admin-only).
- 🔨 **Admin home / KPIs** — GMV, orders, active users, sellers, riders (assemble
  from metrics service + new aggregates).
- 🔨 **Operational health view** — worker failures, stuck orders, scheduled-job
  status; trigger/retry ops tasks (`app/ops/tasks.py`).
- 🔨 **Media library management** — review/remove flagged media
  (admin already bypasses ownership checks in `app/media/routes.py`).
- 🔨 **Feature flags / platform settings** (if/when introduced).

---

## Suggested backend build order

1. **Foundations** (§0): staff RBAC, audit log, admin auth.
2. **Trust & safety core the business asks for**: seller verification (§2),
   moderation queue actions (§7), user suspend/ban (§1).
3. **Money**: refunds, withdrawal/payout processing, wallet adjustments (§6).
4. **Operations**: order status/dispute resolution (§5), delivery ops & failures
   (§8).
5. **Config & catalog**: categories/markets/pricing (§4, §9), gamification (§11).
6. **Comms & metrics polish** (§12, §13).

Then the **web admin app** consumes these endpoints in the same order.
