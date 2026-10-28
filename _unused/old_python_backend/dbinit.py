"""db/schema.sql を流す（db-init サービスが使う）。何度流しても同じになるように書いてある。"""

import os
import time

import psycopg

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://hdt:hdt@postgres:5432/hdt")
SCHEMA = os.environ.get("SCHEMA", "/app/db/schema.sql")

for attempt in range(30):
    try:
        with psycopg.connect(DATABASE_URL) as conn:
            conn.execute(open(SCHEMA, encoding="utf-8").read())
        print("[db-init] schema applied")
        break
    except psycopg.OperationalError as e:
        print(f"[db-init] waiting for postgres: {e}")
        time.sleep(2)
else:
    raise SystemExit("[db-init] could not connect to postgres")
