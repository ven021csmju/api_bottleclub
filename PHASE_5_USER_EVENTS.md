# Phase 5 — User Event Instrumentation (Report)

## Overview

Business operations in the main API now publish user-log events into the
RabbitMQ pipeline built in Phase 4 (`mongo-log-service`). Events are **fired,
not fetched**: no new endpoints were added, the API contract is unchanged, and
a down broker can never break a business operation (failure isolation).

Consumers receive the Phase 4 envelope:

```json
{
  "event_id": "221c9e28-...",
  "event_type": "order_created",
  "version": 1,
  "source": "bottleclub-api",
  "user_id": "42",
  "request_id": "uuid-from-correlation",
  "timestamp": "2026-09-20T08:12:34Z",
  "data": { "order_id": 1, "order_number": "MBR-20260920-0001" }
}
```

- `user_id` comes from the authenticated principal (stringified in the
  envelope only).
- `request_id` is carried through from `CorrelationMiddleware`
  (`request.state.request_id`, honours `X-Request-Id`).
- `data` is schema-validated; the envelope **rejects a curated list of
  sensitive keys** (passwords, tokens, card numbers, finance internals) via a
  Pydantic `model_validator`.

## Entry Points

All services import `app.services.user_events` and call:

- `publish_user_event_sync(...)` — sync FastAPI endpoints run in a worker
  thread, so `asyncio.run(publish_user_log(...))` is safe.
- `await publish_user_event(...)` — async entry points (slip-verify upload).

Both helpers catch every exception and log instead of raising.

## Event Coverage (16 events)

| # | Event type | Emission point | Payload highlights | Notes |
|---|---|---|---|---|
| 1 | `login` | `auth/service.py` | `{success: true}` | After commit + Mongo `sync_log_user_activity`; failed attempts emit nothing |
| 2 | `logout` | `auth/service.py` | `{success: true}` | Only when a refresh-token record was actually revoked |
| 3 | `product_view` | `catalog/router.py` | `{product_id}` | GET `/catalog/products/{id}` |
| 4 | `product_search` | `catalog/router.py` | `{query, result_count}` | GET `/catalog/products?search=` |
| 5 | `product_list_browse` | `catalog/router.py` | `{page, per_page, result_count}` | GET `/catalog/products` without search |
| 6 | `wine_product_search` | `wine_products/router.py` | `{query, result_count}` | Only when search non-empty; plain browse emits nothing |
| 7 | `order_created` | `orders/service.py` | `{order_id, order_number}` | Fresh orders only, not idempotent replays |
| 8 | `purchase_completed` | `orders/service.py` | `{order_id, amount_paid}` | Maps to `checkout_order` (order → paid); NOT `complete_order`, NOT `create_payment` (avoids doubles) |
| 9 | `order_cancelled` | `orders/service.py` | `{order_id}` | Only when status actually changed |
| 10 | `slip_upload` | `slip_verify/router.py` | `{order_id, verification_id, storage_key, status}` | Async entry point; only for statuses where a Verification was created: `{ocr_failed, verified, review, rejected, amount_mismatch, duplicate_reference}` |
| 11 | `review_created` | `reviews/service.py` | `{review_id, product_id}` | After commit |
| 12 | `coupon_validate` | `coupons/service.py` | `{coupon_id, valid}` | Emitted for both valid and invalid (operation succeeded) |
| 13 | `loyalty_earn` | `loyalty/service.py` | `{customer_id, points, transaction_id, reference_type, reference_id}` | After commit |
| 14 | `loyalty_redeem` | `loyalty/service.py` | `{customer_id, points, transaction_id, reference_type, reference_id}` | After commit; insufficient points → 400, nothing emitted |
| 15 | `refund_created` | `refunds/service.py` + `payments/service.py` | `{refund_id, order_id}` | Both `RefundService.create_refund` and `PaymentService.process_refund` publish |
| 16 | `return_created` | `returns/service.py` | `{order_id, return_id}` | After commit |

**18 instrumented call sites** produce these 16 events (catalog emits 3
distinct types; `refund_created` is emitted from two services).

## Constraints Honoured

- No new logging endpoints (events are produced, not queried).
- Response schemas untouched; only optional trailing `request_id: str = ""`
  parameters were added to internal service signatures.
- Sensitive data is never placed in `data` payloads; the envelope rejects it.
- Publish failure is isolated (never raises; broker down = silent no-op with
  ERROR log).

## Documents / Files Changed

- `rabbitmq/` — vendored Phase 4 publisher: `__init__.py`, `schemas.py`,
  `redaction.py` (SENSITIVE_KEYS + helpers), `connection.py`, `topology.py`,
  `publisher.py`.
- `app/config/settings.py`, `.env.example` — RMQ broker/topology settings.
- `requirements.txt` — added `pika==1.3.2`.
- `app/services/user_events.py` — `new_event_id`, `build_user_event`,
  async/sync publish helpers (never raise).
- Domains instrumented: auth, catalog, wine_products, orders, slip_verify,
  reviews, coupons, loyalty, refunds, payments, returns.

## Pre-Existing Bugs Fixed (discovered by the integration tests)

These were latent bugs, unrelated to Phase 4/5 features, surfaced by the new
event instrumentation tests:

1. `LoyaltyService.redeem_points` stored positive `points`, violating the
   `ck_loyalty_txn_math_correct` constraint (`points_after = points_before + points`).
   Now stores `-points`, matching the checkout redemption path.
2. `SlipVerifyRepository.create_verification` / `update_verification_status` /
   `create_attempt` wrote `Decimal` into `JSONB` `risk_score` columns → every
   slip upload 500ed with `TypeError: Object of type Decimal is not JSON
   serializable`. Risk scores are now stored as JSON numbers (`float`),
   matching `float(verification.risk_score)` reads.
3. `ReturnService.create_return` never set `organization_id` on the `Return`
   row (NOT NULL) → 500. Now set from the caller's org.

## Test Results

- New unit tests `tests/unit/test_user_events.py` — **16 passed** (envelope
  fields, unique `event_id`, tz-aware timestamp, sensitive-key rejection,
  redaction, never-raise behaviour).
- New integration tests `tests/integration/test_user_events_instrumentation.py`
  — **23 passed** (real API operations emit the right event with
  `user_id`/`request_id`; failed operations emit nothing; broken publisher
  never breaks login; slip upload emits on OCR failure).
- `mongo-log-service` suite — **117 passed** (Phase 4 untouched).
- Full `api` suite — **181 passed, 5 skipped, 1 failed**; the only failure is
  the pre-existing `tests/unit/test_mongodb_service.py::test_created_at_recorded`
  (pymongo returns naive datetimes; unrelated to this work).