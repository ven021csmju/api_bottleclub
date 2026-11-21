#!/usr/bin/env bash
# Production database steps as bottleclub_owner (Phase 49 runbook, docs/runbooks/phase49-deploy.md).
# The owner runs it as root in a terminal; Claude never does.
#
#   sudo scripts/ops/prod_db.sh backup <label>    pg_dump -Fc -> $BACKUP_DIR/<label>-<stamp>.dump (600),
#                                                 kept only if pg_restore --list reads it
#   sudo scripts/ops/prod_db.sh apply <file.sql> [-v name=value]  one migration / grants file,
#                                                 ON_ERROR_STOP, asks [y/N]
#   sudo scripts/ops/prod_db.sh check <file.sql>  a read-only check (the file's own READ ONLY ... ROLLBACK)
#
# Credentials: OWNER_PSQL_URL of /etc/bottleclub/owner.env, turned into PG* variables of this
# process only (never a command-line argument, never printed). The target must be
# 127.0.0.1:5433/bottleclub_prod. OWNER_ENV / EXPECT_DB / BACKUP_DIR exist to rehearse it on the
# test cluster; production never sets them.
set -euo pipefail
die() { echo "prod_db: $*" >&2; exit 1; }

OWNER_ENV=${OWNER_ENV:-/etc/bottleclub/owner.env}
EXPECT_DB=${EXPECT_DB:-127.0.0.1:5433/bottleclub_prod}
BACKUP_DIR=${BACKUP_DIR:-/var/backups/bottleclub/pg}
PG_BIN=/usr/lib/postgresql/16/bin
cmd=${1:-}; arg=${2:-}; extra=("${@:3}")
[[ $cmd =~ ^(backup|apply|check)$ && -n $arg ]] || die "usage: prod_db.sh backup <label> | apply <file.sql> | check <file.sql>"
[[ -r $OWNER_ENV ]] || die "cannot read $OWNER_ENV (run with sudo)"

OWNER_PSQL_URL=$(set -a; . "$OWNER_ENV"; printf %s "${OWNER_PSQL_URL:-}")
[[ -n $OWNER_PSQL_URL ]] || die "OWNER_PSQL_URL not set in $OWNER_ENV"
eval "$(URL="$OWNER_PSQL_URL" python3 -I -c '
import os, shlex, urllib.parse as u
p = u.urlsplit(os.environ["URL"])
for k, v in (("PGHOST", p.hostname), ("PGPORT", p.port), ("PGUSER", u.unquote(p.username or "")),
             ("PGPASSWORD", u.unquote(p.password or "")), ("PGDATABASE", p.path.lstrip("/"))):
    print("export %s=%s" % (k, shlex.quote(str(v) if v else "")))
')"
unset OWNER_PSQL_URL
target="$PGHOST:$PGPORT/$PGDATABASE"
[[ $target == "$EXPECT_DB" ]] || die "refused: target $target is not $EXPECT_DB"
echo "prod_db: $cmd on $target as $PGUSER"

case $cmd in
backup)
    [[ $arg =~ ^[a-z0-9-]+$ ]] || die "label: lower case, digits, dashes"
    install -d -m 0700 "$BACKUP_DIR"
    f=$BACKUP_DIR/$PGDATABASE-$arg-$(date +%Y%m%d-%H%M%S).dump
    umask 077
    "$PG_BIN/pg_dump" --format=custom --compress=6 --file="$f.part" || { rm -f "$f.part"; die "pg_dump failed"; }
    list=$("$PG_BIN/pg_restore" --list "$f.part") || { rm -f "$f.part"; die "pg_restore --list cannot read it"; }
    mv "$f.part" "$f"
    echo "prod_db: OK $f $(du -h "$f" | cut -f1); entries: $(grep -c ';' <<<"$list"), table data: $(grep -c 'TABLE DATA' <<<"$list")"
    grep -q 'TABLE DATA public schema_migrations' <<<"$list" || die "no schema_migrations data in the dump"
    ;;
apply|check)
    [[ -r $arg && $arg == *.sql ]] || die "not a readable .sql file: $arg"
    if [[ $cmd == apply ]]; then
        [[ -t 0 ]] || die "no TTY: run in a terminal"
        read -r -p "apply $(basename "$arg") to $target as $PGUSER? [y/N] " answer
        [[ $answer == [yY] ]] || die "aborted"
    fi
    "$PG_BIN/psql" -X -q -P pager=off -v ON_ERROR_STOP=1 "${extra[@]}" -f "$arg"
    echo "prod_db: done $(basename "$arg")"
    ;;
esac
