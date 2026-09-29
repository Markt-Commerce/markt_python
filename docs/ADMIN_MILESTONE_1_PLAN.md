# Admin — Milestone 1 Plan (§0 Foundations, §1 Users, §2 Seller verification)

Scope from [ADMIN_ACTIONS.md](./ADMIN_ACTIONS.md). Backend only. Branch:
`feature/admin` (off `develop`). Optional per-increment sub-branches.
Reviewed and committed by the maintainer after each increment.

## Decisions locked
- **RBAC:** lightweight — new `User.admin_role` string column + a permission
  matrix defined in code (`app/admin/permissions.py`). `is_admin` stays as the
  master gate; `super_admin` role implies all permissions. Roles are set only in
  the DB / by a super_admin.
- **Admin auth:** reuse the existing flask-login session + gate. **2FA and
  impersonation are deferred** to a later milestone (assumed default — flag if
  you want either pulled into M1).
- **Home of the admin API:** a new cohesive module `app/admin/` mounted at
  `/api/v1/admin`, registered via `main/routes.py`. Domain mutations reuse
  existing model methods/services; the admin layer orchestrates + audits.

## Conventions followed (from existing code)
- flask-smorest `Blueprint` + `MethodView`, `@bp.arguments`/`@bp.response`.
- marshmallow schemas per module; `PaginationQueryArgs` + `Paginator` for lists.
- `session_scope()` for writes, `read_scope()` for read paths.
- Errors via `app.libs.errors` (`NotFoundError`, `ValidationError`, ...).
- Gating via decorators in `app/libs/decorators.py`.

---

## Increment 1 — Foundations (RBAC + audit + admin module)
**Review point 1.**
- `User.admin_role` column (nullable String; null = not staff).
- `app/admin/permissions.py`: `AdminRole` enum + `ROLE_PERMISSIONS` matrix +
  `has_permission(user, perm)`; `super_admin` ⇒ all.
- Rework `app/libs/decorators.py`: `_has_permission` delegates to the matrix;
  `require_permission(perm)` used for admin perms. Keep `admin_required` working.
- `app/admin/models.py`: `AdminAuditLog` (actor_id, action, target_type,
  target_id, reason, before JSON, after JSON, ip, created_at).
- `app/admin/services.py`: `AdminAuditService.record(...)`.
- `app/admin/routes.py`: `admin_bp` at `/admin`; `GET /admin/me` (returns the
  caller's admin_role + resolved permissions) as a sanity endpoint.
- Register `"admin"` in `main/routes.py` module list.
- Alembic migration (admin_role column + admin_audit_logs table).
- Tests: permission matrix, gate behavior, audit record, `/admin/me`.

## Increment 2 — User management (§1)
**Review point 2.** Endpoints under `/admin/users` (each audited, permission-gated):
- `GET /admin/users` — list/search (email, username, id, role, status), paginated.
- `GET /admin/users/{id}` — detail (buyer/seller sub-profiles, flags, timestamps).
- `POST /admin/users/{id}/suspend` + `/reinstate` — toggle `is_active`
  (`deactivate()`/`activate()`), reason recorded.
- `POST /admin/users/{id}/ban` — soft ban (login blocked); distinct from user's
  own self-deletion path.
- `POST /admin/users/{id}/verify-email` and `/resend-verification`.
- `POST /admin/users/{id}/force-logout` — revoke sessions/tokens.
- `PATCH /admin/users/{id}` — correct basic profile fields (support).
- `POST /admin/users/{id}/roles` — enable/disable buyer/seller accounts.
- (Impersonation intentionally deferred.)
- Schemas + tests.

## Increment 3 — Seller verification & shop (§2)
**Review point 3.** Endpoints under `/admin/sellers` (audited, gated):
- `GET /admin/sellers` — list with `verification_status` /
  `market_verification_status` filters (verification queue).
- `GET /admin/sellers/{id}` — detail incl. submitted verification data + payout.
- `POST /admin/sellers/{id}/verify` → `VERIFIED`.
- `POST /admin/sellers/{id}/reject` (reason) → `REJECTED`.
- `POST /admin/sellers/{id}/suspend` + `/unsuspend` → `SUSPENDED` / restore.
- `POST /admin/sellers/{id}/market-verification` — confirm/override a `FLAGGED`
  market match (`MarketVerificationStatus`).
- `PATCH /admin/sellers/{id}/payout` — edit/verify payout bank details.
- `POST /admin/sellers/{id}/feature` + `/unfeature` — shop feature flag
  (add a `is_featured` column if none exists).
- Schemas + tests.

---

## Out of scope for M1 (later milestones)
2FA enforcement, impersonation, orders/disputes (§5), finance (§6),
moderation queue UI actions beyond existing resolve (§7), delivery ops (§8),
and the web admin app (consumes these endpoints afterward).

## Verification per increment
`pytest` for the touched module + `flask db upgrade` clean apply; black-format
(repo style, see recent commits). No commits made by me — left for maintainer
review.
