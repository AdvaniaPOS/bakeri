"""Legg til products.is_active_overridden (BOOLEAN, default false)."""
from sqlalchemy import text
from app.database import engine

DDL = [
    "ALTER TABLE products ADD COLUMN IF NOT EXISTS is_active_overridden BOOLEAN NOT NULL DEFAULT FALSE",
]

def main():
    with engine.begin() as conn:
        for stmt in DDL:
            print(f"-> {stmt}")
            conn.execute(text(stmt))
    print("OK")

if __name__ == "__main__":
    main()
