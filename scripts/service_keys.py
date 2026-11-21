"""Service keys (X-Service-Key) for server-to-server callers, on the database
of DATABASE_URL (the API's environment).

    python -m scripts.service_keys create --name storefront --org-id 1 \
        --scope customers.lookup --scope customers.create --scope loyalty.read \
        --out ~/storefront-service-key.txt
    python -m scripts.service_keys list
    python -m scripts.service_keys revoke --id 3

create shows the key once: written to --out (a new file, mode 600), or
printed when --out is not given. Only its sha256 is stored, so a lost key
cannot be shown again: revoke it and create another. Nothing here logs a key.

customers.read (the whole list) is retired (Phase 49): a key still holding it
is refused (401 SERVICE_KEY_RETIRED) and 025 revokes it; create a new one.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.db.models import Organization, ServiceKey  # noqa: E402
from app.middleware.service_key import SCOPES, new_key  # noqa: E402
from app.shared.security import hash_token  # noqa: E402


def create(db: Session, name: str, org_id: int, scopes: list[str]) -> tuple[ServiceKey, str]:
    unknown = sorted(set(scopes) - set(SCOPES))
    if unknown or not scopes:
        raise SystemExit(f"scopes must be some of {', '.join(SCOPES)} (got: {', '.join(unknown) or 'none'})")
    if db.get(Organization, org_id) is None:
        raise SystemExit(f"no organization {org_id}")
    raw = new_key()
    key = ServiceKey(
        organization_id=org_id, name=name.strip()[:100], key_prefix=raw[:12],
        key_hash=hash_token(raw), scopes=sorted(set(scopes)),
    )
    db.add(key)
    db.commit()
    return key, raw


def revoke(db: Session, key_id: int) -> ServiceKey:
    key = db.get(ServiceKey, key_id)
    if key is None:
        raise SystemExit(f"no service key {key_id}")
    if key.revoked_at is None:
        key.revoked_at = datetime.now(timezone.utc)
        db.commit()
    return key


def listing(db: Session) -> list[str]:
    rows = db.scalars(select(ServiceKey).order_by(ServiceKey.id)).all()
    return [
        f"{k.id}\t{k.name}\torg={k.organization_id}\t{k.key_prefix}…\t{','.join(k.scopes)}\t"
        f"last_used={k.last_used_at or '-'}\t{'REVOKED ' + str(k.revoked_at) if k.revoked_at else 'active'}"
        for k in rows
    ]


def _write_once(path: Path, raw: str) -> None:
    # O_EXCL: never overwrite (another key may be in it); 600 from the start.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(raw + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    c = sub.add_parser("create")
    c.add_argument("--name", required=True)
    c.add_argument("--org-id", type=int, required=True)
    c.add_argument("--scope", action="append", default=[], choices=SCOPES)
    c.add_argument("--out", type=Path, help="write the key to this new file (600) instead of printing it")
    sub.add_parser("list")
    r = sub.add_parser("revoke")
    r.add_argument("--id", type=int, required=True)
    args = parser.parse_args(argv)

    from app.db.session import SessionLocal

    with SessionLocal() as db:
        if args.command == "create":
            key, raw = create(db, args.name, args.org_id, args.scope)
            if args.out:
                _write_once(args.out.expanduser(), raw)
                print(f"created service key {key.id} ({key.key_prefix}…); the key is in {args.out} (600)")
            else:
                print(f"created service key {key.id}; the key (shown once, store it now):")
                print(raw)
        elif args.command == "list":
            print("\n".join(listing(db)) or "no service keys")
        else:
            key = revoke(db, args.id)
            print(f"service key {key.id} ({key.name}) revoked at {key.revoked_at}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
