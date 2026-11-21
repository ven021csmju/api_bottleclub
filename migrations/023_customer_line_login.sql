-- Customer accounts for LINE Login (the LINE part of Phase 48c, brought
-- forward; docs/design/phase48-customer-accounts.md 1.2).
--
--   customer_accounts     a customer's login, 1:1 with customers (profile,
--                         points), never a staff users row. All columns of the
--                         design; email/password stay NULL for a LINE-only
--                         account (48a uses them for email sign-up).
--   customer_identities   a provider account (google/line) by its subject
--                         (sub), never by email.
--   auth_exchange_codes   one-time codes (sha256 only, 60 s) the LINE callback
--                         hands the frontend; POST /auth/exchange uses one up.
--
-- New tables only: nothing existing is locked or changed.
--
-- Deploy: apply 023, then the code (GET /auth/line*, POST /auth/exchange and
-- GET /customer/me read these tables). The code before it never reads them.
--
-- Idempotent.

BEGIN;

SET LOCAL lock_timeout = '5s';

DO $$
BEGIN
    IF to_regclass('public.schema_migrations') IS NULL THEN
        RAISE EXCEPTION 'schema_migrations is missing: run bootstrap_schema.py first';
    END IF;
    IF EXISTS (SELECT 1 FROM schema_migrations WHERE version = '023') THEN
        RAISE NOTICE '023 already applied: nothing to do';
        RETURN;
    END IF;

    CREATE TABLE IF NOT EXISTS customer_accounts (
        id                      bigserial PRIMARY KEY,
        organization_id         bigint NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
        customer_id             bigint NOT NULL UNIQUE REFERENCES customers(id) ON DELETE RESTRICT,
        email                   varchar(255),
        email_verified_at       timestamptz,
        password_hash           varchar(255),
        password_changed_at     timestamptz,
        phone_pending           varchar(50),
        status                  varchar(20) NOT NULL DEFAULT 'active',
        age_verified_at         timestamptz,
        age_verified_by         bigint REFERENCES users(id) ON DELETE RESTRICT,
        age_verified_branch_id  bigint REFERENCES branches(id) ON DELETE RESTRICT,
        last_login_at           timestamptz,
        created_at              timestamptz NOT NULL DEFAULT now(),
        updated_at              timestamptz NOT NULL DEFAULT now(),
        deleted_at              timestamptz,
        CONSTRAINT ck_customer_account_status CHECK (status IN ('active', 'locked', 'deleted')),
        CONSTRAINT ck_customer_account_deleted_email CHECK (status <> 'deleted' OR email IS NULL),
        CONSTRAINT ck_customer_account_age_verified CHECK ((age_verified_at IS NULL) = (age_verified_by IS NULL))
    );
    CREATE UNIQUE INDEX IF NOT EXISTS uq_customer_account_org_email
        ON customer_accounts (organization_id, email) WHERE email IS NOT NULL;

    CREATE TABLE IF NOT EXISTS customer_identities (
        id                   bigserial PRIMARY KEY,
        customer_account_id  bigint NOT NULL REFERENCES customer_accounts(id) ON DELETE CASCADE,
        provider             varchar(20) NOT NULL,
        provider_subject     varchar(255) NOT NULL,
        email_at_link        varchar(255),
        linked_at            timestamptz NOT NULL DEFAULT now(),
        last_used_at         timestamptz,
        CONSTRAINT ck_customer_identity_provider CHECK (provider IN ('google', 'line')),
        CONSTRAINT uq_customer_identity_subject UNIQUE (provider, provider_subject),
        CONSTRAINT uq_customer_identity_account_provider UNIQUE (customer_account_id, provider)
    );

    CREATE TABLE IF NOT EXISTS auth_exchange_codes (
        id                   bigserial PRIMARY KEY,
        code_hash            varchar(64) NOT NULL UNIQUE,
        customer_account_id  bigint NOT NULL REFERENCES customer_accounts(id) ON DELETE CASCADE,
        expires_at           timestamptz NOT NULL,
        used_at              timestamptz,
        created_at           timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX IF NOT EXISTS ix_auth_exchange_codes_expires ON auth_exchange_codes (expires_at);
    RAISE NOTICE '023: customer_accounts, customer_identities, auth_exchange_codes';

    INSERT INTO schema_migrations (version, note)
    VALUES ('023', 'customer_accounts, customer_identities, auth_exchange_codes (LINE Login)');
END
$$;

COMMIT;
