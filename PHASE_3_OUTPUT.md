# Phase 3 — The Bottle Club POS: Identity, Security, Audit, Multi-Branch, RBAC

> **Continuity from Phase 1-2**: All entity names, field names, and IDs match Phase 1's entity list exactly. Transactional flows reference Phase 2's business rules. No entity or field renaming without explicit flagging.

---

## 16. Multi-Branch Architecture

### 16.1 Current Design Assessment

Phase 1 established that `User.branchId` is **not sufficient**. Here's why:

**Scenario**: Employee "Nook" works as a cashier at Branch A on Monday and Branch B on Tuesday. With a single `branch_id` on the users table, Nook can only be assigned to one branch at a time. This forces the admin to constantly reassign Nook's branch, and it breaks audit trails (which branch did Nook process that order at?).

**Solution already in Phase 1**: The `user_roles` table has the structure:

```
user_roles(user_id, role_id, branch_id)
```

- `branch_id` is **nullable**: null means an org-wide role (e.g., superadmin)
- A user can have **multiple rows** — one per branch + role combination
- Nook can be `(user: Nook, role: Cashier, branch: A)` AND `(user: Nook, role: Cashier, branch: B)`

**This is the correct model.** No additional `user_branches` junction table is needed. The `user_roles` table already serves double duty as both the role assignment and the branch assignment.

### 16.2 Branch Scoping Rules

Every branch-scoped entity must have a `branch_id` column. Here is the complete list:

| Entity | branch_id Column | How It's Scoped |
|---|---|---|
| inventory | branch_id | Each branch has independent stock |
| inventory_lots | branch_id | Lots belong to a specific branch |
| stock_movements | branch_id | Movement recorded at a branch |
| orders | branch_id | Order placed at a branch |
| order_items | *(inherited from order)* | Always via order.branch_id |
| payments | *(inherited from order)* | Always via order.branch_id |
| refunds | *(inherited from order)* | Always via order.branch_id |
| returns | branch_id | Return processed at a branch |
| shifts | branch_id | Shift at a branch register |
| registers | branch_id | Register belongs to a branch |
| purchase_orders | branch_id | PO is for a specific branch |
| purchase_receivings | branch_id | Receiving at a branch |
| stock_transfers | source_branch_id, dest_branch_id | Two branches involved |
| system_settings | branch_id (nullable) | null = org-wide; set = branch override |
| user_roles | branch_id (nullable) | User's role at a specific branch |
| audit_logs | organization_id (nullable) | Org-level audit trail |

### 16.3 Branch Data Isolation at Query Level

**Every query** that reads branch-scoped data MUST include a `branch_id` filter. This is enforced at two layers:

**Layer 1 — Application middleware** (recommended):
```python
# FastAPI dependency that extracts branch_id from the authenticated user's context
def get_current_branch(
    current_user: User = Depends(get_current_user),
    branch_id: int = Header(...)  # Client sends X-Branch-Id header
) -> int:
    # Validate the user has a role at this branch
    if not user_has_role_at_branch(current_user.id, branch_id):
        raise HTTPException(403, "No access to this branch")
    return branch_id
```

**Layer 2 — SQLAlchemy query filters**:
```python
# Every query automatically scopes to the current branch
orders = db.query(Order).filter(
    Order.branch_id == current_branch_id,
    Order.created_at >= start_date
).all()
```

**Exception**: Superadmins can query across branches. The middleware passes a flag indicating cross-branch access, and the query layer conditionally applies the branch filter.

### 16.4 Cross-Branch Operations

Some operations legitimately span branches:
- **Stock transfers**: Involves both source and destination branch
- **Organization-level reports**: Sales across all branches
- **Product catalog management**: Products are org-wide, not per-branch
- **User management**: Users are org-wide with branch-scoped roles

These operations use `organization_id` scoping instead of `branch_id`.

### 16.5 Branch Code Immutability

Branch codes are used in order numbers (`BK1-20260817-0001`). If a branch code changes, all historical order numbers become inconsistent. Therefore:

- Branch codes are **immutable after creation**
- The `branches` table has no `updated_at` concern for the `code` field
- Application layer prevents code updates; database layer enforces via a trigger or application check:

```python
# In the branch update endpoint
if payload.code and payload.code != existing_branch.code:
    raise HTTPException(400, "Branch code cannot be changed after creation")
```

---

## 17. Authentication & RBAC

### 17.1 Authentication Architecture Decision

**Recommendation: Custom JWT-based authentication (not Supabase Auth)**.

Reasons:
1. **Team size (1-2 devs)**: Supabase adds a dependency and learning curve. JWT is well-understood and has mature Python libraries.
2. **Deployment target (single VPS)**: Supabase is a hosted service; a single VPS deployment means you'd be mixing self-hosted and hosted infrastructure unnecessarily.
3. **Full control**: POS systems need fine-grained session control (branch-scoped roles, device tracking, shift binding). Custom auth gives complete control.
4. **No vendor lock-in**: If the team grows or switches frontend frameworks, JWT auth works everywhere.

**If the team later wants Supabase Auth**: The schema is compatible — Supabase Auth stores users in `auth.users` and you'd link to your `users` table. But for v1, custom is simpler.

### 17.2 Token Architecture

**Access Token (JWT)**:
```
Payload:
{
  "sub": user_id,
  "org": organization_id,
  "branches": [branch_id_1, branch_id_2],  // branches user has roles at
  "roles": ["cashier", "manager"],         // unique role names across branches
  "permissions": ["ORDER.CREATE", "PRODUCT.READ", ...],  // flattened permission list
  "iat": issued_at,
  "exp": expires_at  // 15 minutes
}
```

- **Short-lived**: 15 minutes
- **Contains permissions**: Avoids a DB lookup on every request. When permissions change, the next token refresh picks them up.
- **Contains branch list**: Client can show only accessible branches in the branch selector.

**Refresh Token**:
- Stored as a random 64-byte string, hashed with SHA-256 before DB storage
- Stored in `refresh_tokens` table with `user_id`, `token_hash`, `device_info`, `ip_address`, `expires_at`
- **Rotatable**: When a refresh token is used, it's invalidated and a new one is issued (refresh token rotation)
- **Single-use**: Each refresh token can only be used once. If a stolen token is replayed, the rotation invalidates the original session.
- **Expiry**: 7 days (configurable)
- **Device binding**: Each refresh token is tied to a device (user agent string). Logging out revokes all refresh tokens for that user on that device.

### 17.3 Authentication Flow

```
┌─────────┐         ┌─────────┐         ┌──────────┐
│  Client  │         │  API    │         │ Database │
└────┬─────┘         └────┬────┘         └────┬─────┘
     │  POST /auth/login  │                   │
     │  {username, pass}  │                   │
     │───────────────────→│                   │
     │                    │ 1. Lookup user    │
     │                    │──────────────────→│
     │                    │ 2. Verify bcrypt  │
     │                    │ 3. Check status   │
     │                    │ 4. Check lockout  │
     │                    │                   │
     │                    │─── login_attempts INSERT
     │                    │                   │
     │  {access_token,    │                   │
     │   refresh_token,   │                   │
     │   user, branches,  │                   │
     │   permissions}     │                   │
     │←───────────────────│                   │
     │                    │                   │
     │  GET /orders       │                   │
     │  Authorization:    │                   │
     │  Bearer <token>    │                   │
     │───────────────────→│                   │
     │                    │ 5. Decode JWT     │
     │                    │ 6. Check exp      │
     │                    │ 7. Check perm     │
     │                    │ 8. Scope branch   │
     │  {orders data}     │                   │
     │←───────────────────│                   │
     │                    │                   │
     │  POST /auth/refresh│                   │
     │  {refresh_token}   │                   │
     │───────────────────→│                   │
     │                    │ 9. Hash token     │
     │                    │ 10. Lookup + lock │
     │                    │──────────────────→│
     │                    │ 11. Rotate:       │
     │                    │   delete old,     │
     │                    │   insert new      │
     │                    │                   │
     │  {new access_token,│                   │
     │   new refresh_token│                   │
     │  }                 │                   │
     │←───────────────────│                   │
```

### 17.4 Login Process (Detailed)

```python
def login(username: str, password: str, ip_address: str, user_agent: str, db: Session):
    # 1. Find user by username
    user = db.query(User).filter(User.username == username).first()

    # 2. Record login attempt (even if user not found — prevents username enumeration)
    attempt = LoginAttempt(
        user_id=user.id if user else None,
        username=username,
        ip_address=ip_address,
        success=False
    )

    # 3. Validate user exists and is active
    if not user or user.status != UserStatus.ACTIVE:
        db.add(attempt)
        db.commit()
        raise AuthError("Invalid credentials")

    # 4. Check account lockout
    if user.locked_until and user.locked_until > datetime.now(timezone.utc):
        raise AuthError(f"Account locked until {user.locked_until}")

    # 5. Verify password (bcrypt)
    if not bcrypt.verify(password, user.password_hash):
        user.failed_login_attempts += 1
        if user.failed_login_attempts >= 5:
            user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=15)
        db.add(attempt)
        db.commit()
        raise AuthError("Invalid credentials")

    # 6. Success — reset lockout, record success
    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_login_at = datetime.now(timezone.utc)
    user.last_login_ip = ip_address
    attempt.success = True
    db.add(attempt)

    # 7. Generate tokens
    access_token = create_access_token(user)
    refresh_token = create_refresh_token(user, device_info=user_agent, ip=ip_address)

    db.commit()
    return {"access_token": access_token, "refresh_token": refresh_token, "user": serialize_user(user)}
```

### 17.5 RBAC Permission Model

**Permission format**: `MODULE.ACTION` (e.g., `ORDER.CREATE`, `PRODUCT.READ`)

**Complete permission list**:

| Module | Permissions |
|---|---|
| ORDER | ORDER.READ, ORDER.CREATE, ORDER.CANCEL, ORDER.VOID |
| PAYMENT | PAYMENT.READ, PAYMENT.CREATE, PAYMENT.REFUND |
| PRODUCT | PRODUCT.READ, PRODUCT.CREATE, PRODUCT.UPDATE, PRODUCT.DELETE |
| CATEGORY | CATEGORY.READ, CATEGORY.CREATE, CATEGORY.UPDATE, CATEGORY.DELETE |
| INVENTORY | INVENTORY.READ, INVENTORY.ADJUST, INVENTORY.TRANSFER, INVENTORY.RECEIVE |
| PURCHASE | PURCHASE.READ, PURCHASE.CREATE, PURCHASE.APPROVE, PURCHASE.RECEIVE, PURCHASE.CANCEL |
| TRANSFER | TRANSFER.READ, TRANSFER.CREATE, TRANSFER.APPROVE, TRANSFER.SHIP, TRANSFER.RECEIVE |
| CUSTOMER | CUSTOMER.READ, CUSTOMER.CREATE, CUSTOMER.UPDATE |
| LOYALTY | LOYALTY.READ, LOYALTY.ADJUST |
| PROMOTION | PROMOTION.READ, PROMOTION.CREATE, PROMOTION.UPDATE, PROMOTION.DELETE |
| COUPON | COUPON.READ, COUPON.CREATE, COUPON.UPDATE, COUPON.DELETE |
| SHIFT | SHIFT.READ, SHIFT.OPEN, SHIFT.CLOSE, SHIFT.VIEW_CASH |
| REPORT | REPORT.SALES, REPORT.INVENTORY, REPORT.FINANCIAL, REPORT.AUDIT |
| USER | USER.READ, USER.CREATE, USER.UPDATE, USER.DELETE, USER.ASSIGN_ROLE |
| BRANCH | BRANCH.READ, BRANCH.CREATE, BRANCH.UPDATE |
| ROLE | ROLE.READ, ROLE.CREATE, ROLE.UPDATE, ROLE.DELETE, ROLE.ASSIGN_PERMISSION |
| SYSTEM | SYSTEM.READ, SYSTEM.UPDATE, SYSTEM.AUDIT_LOG |
| REGISTER | REGISTER.READ, REGISTER.CREATE, REGISTER.UPDATE |

### 17.6 Default Role Templates

These are seed data — not hardcoded. The system creates them on initialization.

**Cashier**:
```
ORDER.READ, ORDER.CREATE
PAYMENT.READ, PAYMENT.CREATE
PRODUCT.READ
CATEGORY.READ
CUSTOMER.READ, CUSTOMER.CREATE
LOYALTY.READ
SHIFT.READ, SHIFT.OPEN, SHIFT.CLOSE
```

**Branch Manager** (includes all Cashier permissions, plus):
```
ORDER.CANCEL, ORDER.VOID
PAYMENT.REFUND
PRODUCT.CREATE, PRODUCT.UPDATE
INVENTORY.READ, INVENTORY.ADJUST, INVENTORY.TRANSFER, INVENTORY.RECEIVE
PURCHASE.READ, PURCHASE.CREATE, PURCHASE.RECEIVE
TRANSFER.READ, TRANSFER.CREATE, TRANSFER.APPROVE, TRANSFER.SHIP, TRANSFER.RECEIVE
CUSTOMER.UPDATE
LOYALTY.ADJUST
PROMOTION.READ, PROMOTION.CREATE, PROMOTION.UPDATE
COUPON.READ, COUPON.CREATE, COUPON.UPDATE
SHIFT.READ (VIEW_CASH)
REPORT.SALES, REPORT.INVENTORY
USER.READ
```

**Admin** (includes all Branch Manager permissions, plus):
```
PRODUCT.DELETE
CATEGORY.CREATE, CATEGORY.UPDATE, CATEGORY.DELETE
PURCHASE.APPROVE, PURCHASE.CANCEL
TRANSFER.APPROVE
PROMOTION.DELETE
COUPON.DELETE
REPORT.FINANCIAL, REPORT.AUDIT
USER.CREATE, USER.UPDATE, USER.DELETE, USER.ASSIGN_ROLE
BRANCH.CREATE, BRANCH.UPDATE
ROLE.READ, ROLE.CREATE, ROLE.UPDATE, ROLE.DELETE, ROLE.ASSIGN_PERMISSION
SYSTEM.READ, SYSTEM.UPDATE, SYSTEM.AUDIT_LOG
REGISTER.CREATE, REGISTER.UPDATE
```

**Superadmin**:
- Has ALL permissions, branch-independent (branch_id = null in user_roles)
- Can access all branches without explicit branch assignment
- Only one or two superadmin accounts should exist

### 17.7 Authorization Enforcement Point

Authorization is enforced in a **FastAPI dependency chain** that runs before every protected endpoint:

```python
# Dependency chain (executed in order for every request):

# 1. Extract and validate JWT from Authorization header
current_user = Depends(get_current_user)

# 2. Extract branch_id from X-Branch-Id header (for branch-scoped endpoints)
branch_id = Depends(get_current_branch)

# 3. Check required permission
def require_permission(permission_code: str):
    def checker(user = Depends(get_current_user)):
        if permission_code not in user.permissions:
            raise HTTPException(403, f"Missing permission: {permission_code}")
        return user
    return checker

# 4. Usage in endpoint:
@router.post("/orders", dependencies=[Depends(require_permission("ORDER.CREATE"))])
def create_order(
    branch_id: int = Depends(get_current_branch),
    current_user: User = Depends(get_current_user),
    ...
):
    # branch_id and current_user are guaranteed valid and authorized at this point
    ...
```

**Why check in dependency, not middleware**: Middleware runs before route handlers and doesn't know which permission is needed. Dependencies are per-route and declarative — each endpoint declares exactly what it needs.

### 17.8 Logout & Session Revocation

```
POST /auth/logout
Authorization: Bearer <access_token>

1. Decode JWT to get user_id
2. Delete all refresh_tokens for this user + device (or just the current one)
3. Access token remains valid until expiry (15 min) — this is acceptable for POS
```

**For immediate access token invalidation** (optional, higher security):
- Maintain a token blacklist in Redis (key: token_jti, TTL: token expiry)
- Check the blacklist on every request
- This adds Redis dependency for every authenticated request — weigh against the 15-minute window

**v1 recommendation**: No token blacklist. Accept the 15-minute window. Refresh token rotation handles session security adequately for a POS system.

### 17.9 Password Reset Flow

```
POST /auth/password-reset-request
Body: { email }

1. Find user by email
2. If not found: return success (don't reveal whether email exists)
3. Generate a password reset token (random, time-limited, single-use)
4. Store hash of token in users table (or a separate password_resets table)
5. Send email with reset link (or for v1: display the token in a secure admin panel)

POST /auth/password-reset
Body: { token, new_password }

1. Hash the provided token
2. Find user with matching token_hash AND token not expired
3. Update password_hash to bcrypt(new_password)
4. Clear the token
5. Revoke all refresh_tokens for this user (force re-login everywhere)
```

### 17.10 MFA Feasibility

**v1**: Not implemented. The schema supports adding it:
- Add `mfa_enabled BOOLEAN` and `mfa_secret VARCHAR(32)` to users table
- After password verification, if mfa_enabled = true, require TOTP code
- For a POS system running on a single VPS behind a counter, MFA adds friction. Evaluate after v1 launch based on threat model.

---

## 18. Security Architecture

### 18.1 Password Hashing

- **Algorithm**: bcrypt with auto-generated salt, cost factor 12
- **Library**: `passlib[bcrypt]` (Python)
- **Storage**: `password_hash` column stores the full bcrypt hash (60 characters)
- **Never**: Store plaintext, MD5, SHA-1, or unsalted hashes

```python
from passlib.context import CryptContext
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=12)

# Hash
hashed = pwd_context.hash("user_password")

# Verify
is_valid = pwd_context.verify("user_password", hashed)
```

### 18.2 JWT Security

| Aspect | Configuration |
|---|---|
| Algorithm | HS256 (symmetric) for simplicity; RS256 if multi-service later |
| Secret key | 256-bit random string, loaded from environment variable, never in code |
| Access token expiry | 15 minutes |
| Refresh token expiry | 7 days |
| Issuer | `the-bottle-club-pos` |
| Audience | `the-bottle-club-api` |
| Token storage (client) | Access token in memory (JavaScript variable); refresh token in httpOnly cookie or memory |
| Token transmission | `Authorization: Bearer <token>` header |

**Never store tokens in localStorage** — vulnerable to XSS. Use httpOnly, Secure, SameSite=Strict cookies for refresh tokens; access tokens in memory only.

### 18.3 Cookie Configuration (Refresh Token)

```python
response.set_cookie(
    key="refresh_token",
    value=refresh_token,
    httponly=True,       # Not accessible via JavaScript
    secure=True,         # HTTPS only
    samesite="strict",   # No cross-origin requests
    max_age=7*24*3600,   # 7 days
    path="/auth"         # Only sent to auth endpoints
)
```

### 18.4 CORS Configuration

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "https://pos.thebottleclub.com"],
    allow_credentials=True,   # Required for cookies
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-Branch-Id", "X-Idempotency-Key"],
    max_age=600              # Cache preflight for 10 minutes
)
```

### 18.5 Rate Limiting

**Using Redis** (already in the tech stack):

```python
# Login endpoint: 5 attempts per minute per IP
@limiter.limit("5/minute")
@router.post("/auth/login")
def login(...): ...

# General API: 100 requests per minute per user
@limiter.limit("100/minute")
@router.get("/orders")
def get_orders(...): ...

# Order creation: 10 per minute per user (prevent double-tap)
@limiter.limit("10/minute")
@router.post("/orders")
def create_order(...): ...

# Password reset: 3 requests per hour per IP
@limiter.limit("3/hour")
@router.post("/auth/password-reset-request")
def request_password_reset(...): ...
```

**Library**: `slowapi` (integrates with FastAPI, uses Redis backend)

### 18.6 CSRF Protection

- **Access tokens**: Sent via `Authorization` header, not cookies → CSRF not applicable
- **Refresh tokens**: If stored in httpOnly cookies, CSRF applies. Mitigation:
  - SameSite=Strict cookie attribute (prevents cross-origin sending)
  - CSRF token in a separate non-httpOnly cookie that JavaScript reads and sends as a header
  - Or: use the double-submit cookie pattern

**v1 recommendation**: SameSite=Strict is sufficient for a POS system on a single domain.

### 18.7 Input Validation & Sanitization

- **Pydantic validation**: All request bodies validated through Pydantic schemas (type, range, format)
- **SQL injection**: SQLAlchemy ORM uses parameterized queries — no raw SQL concatenation
- **XSS**: API returns JSON, not HTML. The frontend (Next.js) handles HTML escaping. No XSS risk in the API layer itself.
- **SSRF**: No user-supplied URLs are fetched by the server (except optional webhook for payment providers, which should be allowlisted)
- **File upload** (if needed for product images): Validate MIME type, limit file size (5MB), store outside webroot, serve via signed URL

### 18.8 Secrets Management

| Secret | Storage |
|---|---|
| Database URL | `.env` file, never committed to git |
| JWT secret key | `.env` file, never committed to git |
| Redis URL | `.env` file |
| Payment provider API keys | `.env` file |
| SMTP credentials (if email) | `.env` file |

**Rules**:
- `.env` is in `.gitignore`
- `.env.example` contains placeholder values, no real secrets
- In production: use environment variables set at the container/OS level, not `.env` files
- Never log secrets, never include in error messages, never put in API responses

### 18.9 Sensitive Data Protection

**Must never be exposed to the browser**:
- `users.password_hash`
- `refresh_tokens.token_hash`
- `login_attempts.ip_address` (except for the current user's own)
- `audit_logs.before_data` / `after_data` (if containing password changes)
- `idempotency_keys.request_hash`
- Any `.env` values

**API response filtering**: Pydantic response models explicitly exclude sensitive fields. The `UserResponse` schema does NOT include `password_hash`, `failed_login_attempts`, `locked_until`, or `last_login_ip`.

### 18.10 Brute-Force Protection

**Multi-layer approach**:

1. **Application-level lockout**: After 5 failed attempts, `users.locked_until = NOW() + 15 minutes`
2. **Rate limiting**: 5 login attempts per minute per IP via Redis
3. **Login attempt logging**: Every attempt (success or failure) recorded in `login_attempts` table
4. **Progressive delays** (optional): After 3 failures, add increasing delay before responding (1s, 2s, 4s)

### 18.11 Security Headers

```python
@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response
```

### 18.12 Dependency Security

```bash
# Regularly check for vulnerabilities
pip-audit  # or safety check

# Pin all dependencies in requirements.txt
# Use hash-checking mode in pip
pip install --require-hashes -r requirements.txt
```

---

## 19. Audit Architecture

### 19.1 Audit Log Design

The `audit_logs` table from Phase 1:

| Field | Purpose |
|---|---|
| id | Unique identifier |
| organization_id | Which org (null for system-level) |
| user_id | Who performed the action (null for system) |
| action | What action: CREATE, UPDATE, DELETE, LOGIN, LOGOUT, etc. |
| entity_type | Which table/entity was affected |
| entity_id | Which specific record |
| before_data | JSONB: state before change (for updates/deletes) |
| after_data | JSONB: state after change (for creates/updates) |
| ip_address | Client IP |
| user_agent | Client user agent |
| request_id | UUID correlation ID (same across all events in one request) |
| metadata | JSONB: additional context (e.g., shift_id, order_number) |
| created_at | Immutable timestamp |

### 19.2 DB-Level Immutability Enforcement

```sql
CREATE OR REPLACE FUNCTION prevent_audit_log_modification()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'audit_logs table is immutable — updates and deletes are not allowed';
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_audit_log_immutable
    BEFORE UPDATE OR DELETE ON audit_logs
    FOR EACH ROW
    EXECUTE FUNCTION prevent_audit_log_modification();
```

This trigger makes it **physically impossible** to update or delete audit log rows, even if the application code has a bug. The only way to bypass is a superuser `DISABLE TRIGGER` command, which requires database-level access and should be logged separately.

### 19.3 Operations That MUST Create Audit Events

This is not an exhaustive list — it is the **minimum required** list. Every row in this table represents a non-negotiable audit event:

| Event | entity_type | action | before_data | after_data | Why Required |
|---|---|---|---|---|---|
| User login success | user | LOGIN | null | {last_login_at, last_login_ip} | Security: track access |
| User login failure | user | LOGIN_FAILED | null | {reason} | Security: brute force detection |
| User created | user | CREATE | null | {user fields} | Admin audit |
| User updated | user | UPDATE | {changed fields} | {changed fields} | Admin audit |
| User deleted (soft) | user | DELETE | {is_active: true} | {deleted_at} | Admin audit |
| Role assigned to user | user_role | CREATE | null | {user_id, role_id, branch_id} | Security: permission change |
| Role revoked from user | user_role | DELETE | {user_id, role_id, branch_id} | null | Security: permission change |
| Role permissions changed | role_permission | CREATE/DELETE | null/old | new/null | Security: permission change |
| Order created | order | CREATE | null | {order summary} | Financial: new transaction |
| Order status changed | order | UPDATE | {status: old} | {status: new} | Financial: state change |
| Order cancelled | order | CANCEL | {status} | {cancelled_at} | Financial: void record |
| Payment completed | payment | CREATE | null | {amount, method, status} | Financial: money received |
| Payment failed | payment | UPDATE | {status: PENDING} | {status: FAILED} | Financial: failed transaction |
| Refund processed | refund | CREATE | null | {amount, method} | Financial: money returned |
| Return processed | return | CREATE | null | {items, reason} | Financial: product return |
| Stock adjusted | stock_movement | CREATE | null | {type, qty, reason} | Inventory: manual change |
| Stock transfer created | stock_transfer | CREATE | null | {source, dest, items} | Inventory: movement |
| Stock transfer approved | stock_transfer | UPDATE | {status} | {status, approved_by} | Inventory: authorization |
| Shift opened | shift | CREATE | null | {opening_cash, register} | Cash: drawer opened |
| Shift closed | shift | UPDATE | {status: OPEN} | {closing, expected, difference} | Cash: reconciliation |
| Cash in/out | shift_cash_movement | CREATE | null | {type, amount, reason} | Cash: drawer changes |
| Product created/updated/deleted | product | CREATE/UPDATE/DELETE | varies | varies | Catalog: product changes |
| System setting changed | system_setting | UPDATE | {old_value} | {new_value} | Config: system changes |
| Purchase order created | purchase_order | CREATE | null | {po summary} | Financial: procurement |
| Purchase order approved | purchase_order | UPDATE | {status} | {status, approved_by} | Financial: authorization |

### 19.4 Audit Log Middleware (Application Layer)

```python
# FastAPI middleware that creates audit events

class AuditContext:
    """Captures request context for audit logging"""
    def __init__(self, request: Request, user: User):
        self.user_id = user.id
        self.organization_id = user.organization_id
        self.ip_address = request.client.host
        self.user_agent = request.headers.get("user-agent", "")
        self.request_id = str(uuid4())  # Generated per request

def log_audit(
    db: Session,
    ctx: AuditContext,
    action: str,
    entity_type: str,
    entity_id: int = None,
    before_data: dict = None,
    after_data: dict = None,
    metadata: dict = None
):
    entry = AuditLog(
        organization_id=ctx.organization_id,
        user_id=ctx.user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        before_data=before_data,
        after_data=after_data,
        ip_address=ctx.ip_address,
        user_agent=ctx.user_agent,
        request_id=ctx.request_id,
        metadata=metadata
    )
    db.add(entry)
    # Do NOT commit here — let the calling transaction commit
    # This ensures audit log is written atomically with the business event
```

**Important**: The audit log INSERT happens **within the same transaction** as the business event. If the business event rolls back, the audit log also rolls back. This ensures audit logs never record events that didn't actually happen.

### 19.5 Audit Log Queries

Common audit queries and their performance characteristics:

```sql
-- "Show me all activity for user 42 in the last 7 days"
SELECT * FROM audit_logs
WHERE user_id = 42 AND created_at >= NOW() - INTERVAL '7 days'
ORDER BY created_at DESC;

-- "Show me all changes to order 1234"
SELECT * FROM audit_logs
WHERE entity_type = 'order' AND entity_id = 1234
ORDER BY created_at;

-- "Show me all financial events at branch BK1 today"
SELECT * FROM audit_logs
WHERE entity_type IN ('order', 'payment', 'refund', 'return')
  AND created_at >= CURRENT_DATE
  AND metadata->>'branch_code' = 'BK1'
ORDER BY created_at;

-- "Who changed this product and when?"
SELECT * FROM audit_logs
WHERE entity_type = 'product' AND entity_id = 100
  AND action = 'UPDATE'
ORDER BY created_at DESC
LIMIT 10;
```

### 19.6 Audit Log Retention & Archival

- **Hot data** (recent 90 days): Kept in the main `audit_logs` table
- **Warm data** (90 days - 1 year): Can be moved to a partitioned table or left in place
- **Cold data** (1 year+): Archive to cold storage (S3, compressed) or leave in DB

**v1 recommendation**: No archival. The table will grow, but at ~10-50 audit events per order and ~500 orders/day, that's ~25,000 rows/day or ~9 million rows/year. PostgreSQL handles this well with proper indexes. Revisit after 1 year.

### 19.7 Request Correlation

Every HTTP request generates a `request_id` (UUID) that is:
1. Generated in middleware at the start of the request
2. Stored in all audit logs created during that request
3. Returned to the client in the `X-Request-Id` response header
4. Can be used to trace all side effects of a single API call

```python
@app.middleware("http")
async def correlation_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-Id", str(uuid4()))
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-Id"] = request_id
    return response
```

---

## Summary of Phase 3 Design Decisions

| Decision | Rationale |
|---|---|
| Custom JWT auth over Supabase | Simpler for 1-2 devs on single VPS; no vendor lock-in; full control over branch-scoped sessions |
| Permissions in JWT payload | Avoids DB lookup on every request; permissions cached until token refresh (15 min max staleness) |
| Refresh token rotation | Single-use tokens prevent stolen token reuse; rotation invalidates the old token |
| No access token blacklist | 15-minute expiry is acceptable for POS; avoids Redis lookup on every request |
| user_roles as branch assignment | One table serves dual purpose (role + branch); no extra junction table |
| Audit log in same transaction as business event | Ensures audit never records events that didn't actually happen |
| DB trigger prevents audit modification | Physical enforcement, not just application-level |
| Branch code immutable | Order numbers depend on branch code; changing it breaks historical references |
| No MFA in v1 | POS behind a counter on a single VPS; evaluate after launch based on threat model |
| Permission format MODULE.ACTION | Scalable, self-documenting, easy to check in code |

---

**End of Phase 3. Ready for Phase 4 (Concurrency, Idempotency, SQLAlchemy Schema, Indexing, Constraints, PostgreSQL Specifics) when you are.**
