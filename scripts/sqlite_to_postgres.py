#!/usr/bin/env python3
"""
One-off copy of the old SQLite database into PostgreSQL.

Target schema must exist first (flask --app app db upgrade).
Usage: python scripts/sqlite_to_postgres.py /app/instance/voice_assistant.db
(DATABASE_URL points to Postgres)
"""
import os
import sys

from sqlalchemy import create_engine, inspect, select, text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from models import db  # noqa: E402

# Parents before children (foreign keys)
TABLES = ["calls", "users", "conversations", "orders", "voice_messages"]


def main(sqlite_path):
    source = create_engine(f"sqlite:///{sqlite_path}")
    target = create_engine(os.environ["DATABASE_URL"])
    source_tables = set(inspect(source).get_table_names())

    with target.begin() as dst:
        for name in TABLES:
            if dst.execute(text(f"SELECT count(*) FROM {name}")).scalar():
                sys.exit(f"Target table {name} is not empty, aborting")

        with source.connect() as src:
            for name in TABLES:
                if name not in source_tables:
                    print(f"{name}: not in source, skipped")
                    continue
                table = db.metadata.tables[name]
                source_columns = {c["name"] for c in inspect(source).get_columns(name)}
                columns = [c.name for c in table.columns if c.name in source_columns]
                # Typed select: model types convert SQLite dates/bools/enums
                rows = [
                    dict(row._mapping)
                    for row in src.execute(select(*[table.c[c] for c in columns]))
                ]
                if rows:
                    dst.execute(table.insert(), rows)
                dst.execute(
                    text(
                        f"SELECT setval(pg_get_serial_sequence('{name}', 'id'), "
                        f"COALESCE((SELECT max(id) FROM {name}), 0) + 1, false)"
                    )
                )
                print(f"{name}: {len(rows)} rows")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
