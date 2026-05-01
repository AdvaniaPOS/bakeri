"""Migrasjon: produksjons-batch, leverings-bekreftelse og svinn-felter.

Legger til:
- products.batch_size              (INT default 1)  -- antall pr. ovns-/deig-batch
- products.production_step         (VARCHAR 100)    -- gruppering, f.eks. 'Ovn 1' / 'Bakebenk'
- products.production_lead_minutes (INT default 0)  -- estimert tid pr. batch i minutter
- order_lines.delivered_quantity   (INT NULL)       -- faktisk levert (sjåfør tikker av)
- order_lines.waste_quantity       (INT default 0)  -- svinn registrert
- order_lines.return_quantity      (INT default 0)  -- retur fra dagligvare
- orders.delivery_photo_url        (VARCHAR 1000)   -- bilde fra sjåfør (URL eller data:)
- users.customer_id                (INT NULL FK)    -- kunde-portal-bruker
"""
from sqlalchemy import text
from app.database import engine

DDL = [
    "ALTER TABLE products ADD COLUMN IF NOT EXISTS batch_size INTEGER NOT NULL DEFAULT 1",
    "ALTER TABLE products ADD COLUMN IF NOT EXISTS production_step VARCHAR(100)",
    "ALTER TABLE products ADD COLUMN IF NOT EXISTS production_lead_minutes INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE order_lines ADD COLUMN IF NOT EXISTS delivered_quantity INTEGER",
    "ALTER TABLE order_lines ADD COLUMN IF NOT EXISTS waste_quantity INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE order_lines ADD COLUMN IF NOT EXISTS return_quantity INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS delivery_photo_url VARCHAR(1000)",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS customer_id INTEGER",
    # FK + indeks for users.customer_id (kun hvis customers-tabell finnes)
    """DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'fk_users_customer_id'
        ) THEN
            ALTER TABLE users
                ADD CONSTRAINT fk_users_customer_id
                FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE SET NULL;
        END IF;
    END$$;""",
    "CREATE INDEX IF NOT EXISTS ix_users_customer_id ON users(customer_id)",
    "CREATE INDEX IF NOT EXISTS ix_products_production_step ON products(tenant_id, production_step)",
]


def main() -> None:
    with engine.begin() as conn:
        for stmt in DDL:
            print(f"-> {stmt.splitlines()[0][:80]} ...")
            conn.execute(text(stmt))
    print("OK")


if __name__ == "__main__":
    main()
