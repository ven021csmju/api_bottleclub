#!/usr/bin/env python3
"""
Cleanup script for Alembic migration files.
Run this on the Ubuntu machine to fix the migration error.

Usage:
    python scripts/fix_migrations.py

This will:
1. Remove ALL old migration files from alembic/versions/
2. Remove __pycache__
3. Verify 001_initial_schema.py exists
"""
import os
import shutil
import sys
from pathlib import Path


def main():
    project_root = Path(__file__).resolve().parents[1]
    versions_dir = project_root / "alembic" / "versions"

    if not versions_dir.exists():
        print(f"ERROR: {versions_dir} does not exist")
        sys.exit(1)

    # 1. Remove __pycache__
    pycache = versions_dir / "__pycache__"
    if pycache.exists():
        shutil.rmtree(pycache)
        print(f"Removed: {pycache}")

    # 2. Remove all .py files except 001_initial_schema.py
    removed = []
    for f in versions_dir.glob("*.py"):
        if f.name == "001_initial_schema.py":
            continue
        if f.name == "__init__.py":
            continue
        if f.name == ".gitkeep":
            continue
        f.unlink()
        removed.append(f.name)
        print(f"Removed: {f.name}")

    if not removed:
        print("No old files to remove (already clean)")
    else:
        print(f"\nRemoved {len(removed)} old migration file(s)")

    # 3. Verify 001_initial_schema.py exists
    target = versions_dir / "001_initial_schema.py"
    if target.exists():
        print(f"OK: {target} exists")
    else:
        print(f"ERROR: {target} not found!")
        print("Copy 001_initial_schema.py to alembic/versions/")
        sys.exit(1)

    # 4. List what's in versions/
    print(f"\nCurrent files in {versions_dir}:")
    for f in sorted(versions_dir.iterdir()):
        if f.is_file():
            print(f"  {f.name}")

    print("\nDone! Now run:")
    print("  alembic upgrade head")


if __name__ == "__main__":
    main()
