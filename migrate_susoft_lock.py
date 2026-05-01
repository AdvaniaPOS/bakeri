"""Legg til tenants.susoft_config_locked (BOOLEAN, default TRUE)."""
from sqlalchemy import text
from app.database import engine

DDL = [
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS susoft_config_locked BOOLEAN NOT NULL DEFAULT TRUE",
]

def main():
    with engine.begin() as conn:
        for stmt in DDL:
            print(f"-> {stmt}")
            conn.execute(text(stmt))
    print("OK")

if __name__ == "__main__":
    main()
