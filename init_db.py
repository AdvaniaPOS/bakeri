"""
Initialize database and import customers/products.
Run this script to set up the database from scratch.
"""
import json
import os
from datetime import datetime
from decimal import Decimal
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Import database and models
from app.database import engine, SessionLocal, Base
from app.models import Customer, Product, Route

def create_tables():
    """Create all database tables."""
    print("🗄️  Creating database tables...")
    # Import all models to register them with Base
    from app import models  # noqa: F401
    from app import auth_models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    print("✅ Tables created successfully")

def create_default_routes():
    """Create default delivery routes."""
    session = SessionLocal()
    try:
        # Check if routes exist
        existing = session.query(Route).count()
        if existing > 0:
            print(f"⏭️  Routes already exist ({existing}), skipping...")
            return
        
        default_routes = [
            Route(name="Rute 1 - Kongsberg", description="Kongsberg sentrum og nærområder", delivery_days=[1,2,3,4,5], sort_order=1),
            Route(name="Rute 2 - Notodden", description="Notodden og omegn", delivery_days=[1,3,5], sort_order=2),
            Route(name="Rute 3 - Hokksund", description="Hokksund og Nedre Eiker", delivery_days=[2,4], sort_order=3),
        ]
        
        for route in default_routes:
            session.add(route)
        
        session.commit()
        print(f"✅ Created {len(default_routes)} default routes")
    except Exception as e:
        session.rollback()
        print(f"❌ Error creating routes: {e}")
    finally:
        session.close()

def import_customers():
    """Import customers from susoft_customers_full.json."""
    # Get absolute path relative to this script
    script_dir = os.path.dirname(os.path.abspath(__file__))
    json_path = os.path.join(script_dir, "data", "susoft_customers_full.json")
    
    if not os.path.exists(json_path):
        print("❌ susoft_customers_full.json not found")
        return 0
    
    with open(json_path, "r", encoding="utf-8") as f:
        customers_data = json.load(f)
    
    print(f"📋 Loaded {len(customers_data)} customers from JSON")
    
    session = SessionLocal()
    imported = 0
    skipped = 0
    seen_ids = set()
    
    try:
        for c in customers_data:
            susoft_id = str(c.get("id", ""))
            
            if not susoft_id:
                skipped += 1
                continue
            
            # Skip duplicates in the JSON
            if susoft_id in seen_ids:
                skipped += 1
                continue
            seen_ids.add(susoft_id)
            
            # Check if customer exists
            existing = session.query(Customer).filter_by(susoft_customer_id=susoft_id).first()
            if existing:
                skipped += 1
                continue
            
            # Build name
            first_name = c.get("firstName", "") or ""
            last_name = c.get("lastName", "") or ""
            display_name = c.get("displayName", "") or ""
            
            if display_name:
                name = display_name
            elif first_name and last_name:
                name = f"{first_name} {last_name}"
            else:
                name = first_name or last_name or f"Kunde {susoft_id}"
            
            # Extract address
            addr = c.get("address") or {}
            
            customer = Customer(
                susoft_customer_id=susoft_id,
                name=name[:255],
                company_name=display_name[:255] if c.get("isCompany") and display_name else None,
                contact_person=first_name[:255] if first_name and not c.get("isCompany") else None,
                email=addr.get("email", "")[:254] if addr.get("email") else None,
                phone=(addr.get("landLinePhone") or addr.get("mobilePhone") or "")[:50] or None,
                street_address=(addr.get("addressLine1") or addr.get("addressLine2") or "")[:500] or None,
                postal_code=addr.get("zipCode", "")[:20] if addr.get("zipCode") else None,
                city=addr.get("city", "")[:100] if addr.get("city") else None,
                country="Norway",
                order_lead_days=14,
                is_active=c.get("isActive", True),
                is_deleted=False
            )
            
            session.add(customer)
            imported += 1
            
            if imported % 50 == 0:
                session.commit()
                print(f"   ... imported {imported} customers")
        
        session.commit()
        print(f"✅ Imported {imported} customers, skipped {skipped}")
        return imported
        
    except Exception as e:
        session.rollback()
        print(f"❌ Error importing customers: {e}")
        import traceback
        traceback.print_exc()
        return 0
    finally:
        session.close()

def import_products():
    """Import products from bakeri_produkter.json."""
    # Get absolute path relative to this script
    script_dir = os.path.dirname(os.path.abspath(__file__))
    json_path = os.path.join(script_dir, "data", "bakeri_produkter.json")
    
    if not os.path.exists(json_path):
        print("❌ bakeri_produkter.json not found")
        return 0
    
    with open(json_path, "r", encoding="utf-8") as f:
        products_data = json.load(f)
    
    print(f"📦 Loaded {len(products_data)} products from JSON")
    
    session = SessionLocal()
    imported = 0
    skipped = 0
    
    try:
        for p in products_data:
            susoft_id = str(p.get("id", ""))
            
            if not susoft_id:
                skipped += 1
                continue
            
            # Check if product exists
            existing = session.query(Product).filter_by(susoft_product_id=susoft_id).first()
            if existing:
                skipped += 1
                continue
            
            product = Product(
                susoft_product_id=susoft_id,
                name=p.get("name", f"Produkt {susoft_id}")[:255],
                description=p.get("description", "")[:1000] if p.get("description") else None,
                barcode=p.get("barcode", "")[:100] if p.get("barcode") else None,
                category=p.get("category", "")[:100] if p.get("category") else None,
                unit=p.get("unit", "stk")[:20],
                default_price=Decimal(str(p.get("retailPrice", 0))),
                cost_price=Decimal(str(p.get("costPrice", 0))) if p.get("costPrice") else None,
                vat_percentage=Decimal(str(p.get("vatPercent", 15))),
                is_active=p.get("active", True),
                is_deleted=False
            )
            
            session.add(product)
            imported += 1
        
        session.commit()
        print(f"✅ Imported {imported} products, skipped {skipped}")
        return imported
        
    except Exception as e:
        session.rollback()
        print(f"❌ Error importing products: {e}")
        import traceback
        traceback.print_exc()
        return 0
    finally:
        session.close()

def main():
    """Run full database initialization."""
    print("\n" + "="*50)
    print("🥐 LAMPELAND BAKERI - DATABASE INITIALIZATION")
    print("="*50 + "\n")
    
    # Step 1: Create tables
    create_tables()
    
    # Step 2: Create default routes
    create_default_routes()
    
    # Step 3: Import customers
    import_customers()
    
    # Step 4: Import products
    import_products()
    
    print("\n" + "="*50)
    print("✅ DATABASE INITIALIZATION COMPLETE")
    print("="*50 + "\n")

if __name__ == "__main__":
    main()
