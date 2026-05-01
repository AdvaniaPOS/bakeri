"""One-off: normaliser product.category til kun blad-segment (siste etter '/')."""
from app.database import SessionLocal
from app.models import Product

def main():
    db = SessionLocal()
    try:
        updated = 0
        for p in db.query(Product).filter(Product.category.isnot(None)).all():
            if not p.category or "/" not in p.category:
                continue
            leaf = p.category.split("/")[-1].strip()
            if leaf and leaf != p.category:
                print(f"  {p.name}: {p.category!r} -> {leaf!r}")
                p.category = leaf
                updated += 1
        db.commit()
        print(f"Oppdaterte {updated} produkter.")
    finally:
        db.close()

if __name__ == "__main__":
    main()
