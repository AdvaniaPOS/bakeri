"""Migrasjon: 2FA / TOTP-felter på users.

Legger til:
- users.totp_secret  (VARCHAR 255 NULL)  -- kryptert
- users.totp_enabled (BOOLEAN default false)
"""
from sqlalchemy import text
from app.database import engine

DDL = [
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_secret VARCHAR(255)",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_enabled BOOLEAN NOT NULL DEFAULT FALSE",
]


def main() -> None:
    with engine.begin() as conn:
        for stmt in DDL:
            print(f"-> {stmt}")
            conn.execute(text(stmt))
    print("OK")


if __name__ == "__main__":
    main()
