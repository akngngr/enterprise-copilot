#!/usr/bin/env python3
"""Connectivity check for the keep-supabase-awake workflow.

Supabase pauses Free-plan projects after 7 days of low API activity, so
something has to touch the database on a schedule. This script does exactly one
thing: prove Postgres is reachable, and say so unambiguously on exit code.

It deliberately does NOT copy anything. The Free plan retains zero backups, and
this job only resets the idle timer — it is not a safety net for data.

Exit codes:
    0  reachable
    1  unreachable, or configuration is unusable

Usage:
    DATABASE_URL=postgresql://... python3 scripts/db_heartbeat.py
"""

from __future__ import annotations

import os
import re
import sys
from urllib.parse import urlparse

# Only ever probe a Supabase host. If DATABASE_URL is pasted wrong, fail loudly
# rather than sending a connection attempt at whatever host is in the secret.
SUPABASE_HOST_SUFFIXES = (".supabase.com", ".supabase.co")
SECRET_PATTERN = re.compile(r"(postgres(?:ql)?://[^:]+:)[^@]+(@)")


def mask(text: str) -> str:
    """Redact the password before anything reaches a CI log."""
    return SECRET_PATTERN.sub(r"\1***\2", text)


def resolve_dsn() -> str:
    dsn = os.environ.get("DATABASE_URL", "").strip()
    if not dsn:
        raise SystemExit(
            "DATABASE_URL is not set.\n"
            "Add it under Settings -> Secrets and variables -> Actions."
        )

    host = urlparse(dsn).hostname or ""
    if not any(host.endswith(suffix) for suffix in SUPABASE_HOST_SUFFIXES):
        raise SystemExit(f"DATABASE_URL host {host!r} is not a Supabase host.")

    return dsn


def main() -> int:
    try:
        dsn = resolve_dsn()
    except SystemExit as error:
        print(f"::error::{error}")
        return 1

    print(f"host: {urlparse(dsn).hostname}")

    try:
        import psycopg2
    except ImportError:
        print("::error::psycopg2 is not installed (pip install psycopg2-binary)")
        return 1

    connection = None
    try:
        connection = psycopg2.connect(
            dsn,
            connect_timeout=15,
            options="-c statement_timeout=10000",
        )
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            value = cursor.fetchone()[0]
    except Exception as error:  # noqa: BLE001 - report anything the driver raises
        print("::error::could not reach the database")
        print(f"{type(error).__name__}: {mask(str(error))}")
        if "tenant" in str(error).lower() or "ENOTFOUND" in str(error):
            print(
                "This looks like a paused free-tier project.\n"
                "Resume it from https://supabase.com/dashboard"
            )
        return 1
    finally:
        if connection is not None:
            connection.close()

    if value != 1:
        print(f"::error::unexpected probe result: {value!r}")
        return 1

    print("database reachable - idle timer reset")
    return 0


if __name__ == "__main__":
    sys.exit(main())