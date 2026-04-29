"""
Script to sync products and customers from SuSoft API.
Run this to populate the local database with SuSoft data.
"""
import os
import sys
from datetime import datetime
from dotenv import load_dotenv
import httpx

# Load environment variables
load_dotenv()

SUSOFT_BASE_URL = os.getenv("SUSOFT_BASE_URL", "https://api.susoft.com:4443")
SUSOFT_USERNAME = os.getenv("SUSOFT_USERNAME")
SUSOFT_PASSWORD = os.getenv("SUSOFT_PASSWORD")
SUSOFT_SHOP_URL_KEY = os.getenv("SUSOFT_SHOP_URL_KEY")

def get_auth_token():
    """Authenticate and get JWT token."""
    print(f"\n🔐 Authenticating with SuSoft API...")
    print(f"   URL: {SUSOFT_BASE_URL}")
    print(f"   User: {SUSOFT_USERNAME}")
    print(f"   Shop: {SUSOFT_SHOP_URL_KEY}")
    
    headers = {"Content-Type": "application/json"}
    if SUSOFT_SHOP_URL_KEY:
        headers["X-Shop-Url-Key"] = SUSOFT_SHOP_URL_KEY
    
    response = httpx.post(
        f"{SUSOFT_BASE_URL}/user/auth",
        json={
            "login": SUSOFT_USERNAME,
            "password": SUSOFT_PASSWORD
        },
        headers=headers,
        timeout=30,
        verify=False  # In case of SSL issues
    )
    
    if response.status_code == 200:
        data = response.json()
        token = data.get("token")
        print(f"   ✅ Authentication successful!")
        return token
    else:
        print(f"   ❌ Authentication failed: {response.status_code}")
        print(f"   Response: {response.text[:500]}")
        return None

def get_headers(token):
    """Build request headers with auth."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    if SUSOFT_SHOP_URL_KEY:
        headers["X-Shop-Url-Key"] = SUSOFT_SHOP_URL_KEY
    return headers

def fetch_products(token):
    """Fetch all products from SuSoft."""
    import time
    print(f"\n📦 Fetching products...")
    
    all_products = []
    page = 0
    page_size = 100
    
    # Try product search with empty criteria first (gets all products)
    print("   Trying /product/search endpoint...")
    response = httpx.post(
        f"{SUSOFT_BASE_URL}/product/search",
        json={"filterGroups": []},
        params={"page": 0, "pageSize": 1000, "activityFlag": "ALL"},
        headers=get_headers(token),
        timeout=60,
        verify=False
    )
    
    if response.status_code == 200:
        products = response.json()
        if products:
            all_products.extend(products)
            print(f"   Found {len(products)} products via search")
    
    # Also try list/modified endpoint with no date filter
    print("   Trying /product/list/modified endpoint...")
    while True:
        response = httpx.get(
            f"{SUSOFT_BASE_URL}/product/list/modified",
            params={"page": page, "pageSize": page_size, "withVariants": "true"},
            headers=get_headers(token),
            timeout=60,
            verify=False
        )
        
        if response.status_code == 429:
            print(f"   ⏳ Rate limited, waiting 5 seconds...")
            time.sleep(5)
            continue
        
        if response.status_code != 200:
            print(f"   ❌ Error fetching products: {response.status_code}")
            print(f"   Response: {response.text[:500]}")
            break
        
        products = response.json()
        if not products:
            break
        
        # Add only unique products
        existing_ids = {p.get("id") for p in all_products}
        new_products = [p for p in products if p.get("id") not in existing_ids]
        all_products.extend(new_products)
        
        print(f"   Page {page + 1}: fetched {len(products)} products (total unique: {len(all_products)})")
        
        if len(products) < page_size:
            break
        page += 1
        time.sleep(1)
    
    # Try fetching by category if we have few products
    if len(all_products) < 10:
        print("   Trying /product/category/tree to find categories...")
        response = httpx.get(
            f"{SUSOFT_BASE_URL}/product/category/tree",
            headers=get_headers(token),
            timeout=60,
            verify=False
        )
        if response.status_code == 200:
            categories = response.json()
            print(f"   Category tree: {categories}")
    
    return all_products

def fetch_customers(token):
    """Fetch all customers from SuSoft."""
    import time
    print(f"\n👥 Fetching customers...")
    
    all_customers = []
    page = 0
    page_size = 100
    
    while True:
        response = httpx.get(
            f"{SUSOFT_BASE_URL}/customer/list",
            params={"page": page, "pageSize": page_size},
            headers=get_headers(token),
            timeout=60,
            verify=False
        )
        
        if response.status_code == 429:
            # Rate limited - wait and retry
            print(f"   ⏳ Rate limited, waiting 5 seconds...")
            time.sleep(5)
            continue
        
        if response.status_code != 200:
            print(f"   ❌ Error fetching customers: {response.status_code}")
            print(f"   Response: {response.text[:500]}")
            break
        
        customers = response.json()
        if not customers:
            break
            
        all_customers.extend(customers)
        print(f"   Page {page + 1}: fetched {len(customers)} customers (total: {len(all_customers)})")
        
        if len(customers) < page_size:
            break
        page += 1
        
        # Small delay to avoid rate limiting
        time.sleep(1)
    
    return all_customers

def save_to_json(data, filename):
    """Save data to JSON file for inspection."""
    import json
    filepath = os.path.join(os.path.dirname(__file__), "data", filename)
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    
    print(f"   💾 Saved to {filepath}")

def print_products_summary(products):
    """Print summary of products."""
    print(f"\n📊 PRODUCTS SUMMARY ({len(products)} total)")
    print("=" * 60)
    
    # Group by category
    categories = {}
    for p in products:
        cat = p.get("category1") or p.get("categoryName") or "Ukategorisert"
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(p)
    
    for cat, items in sorted(categories.items()):
        print(f"\n  {cat} ({len(items)} varer):")
        for item in items[:5]:  # Show first 5
            name = item.get("name", "?")
            price = item.get("retailPrice", 0)
            product_id = item.get("id", "?")
            print(f"    - {name} (kr {price}) [ID: {product_id}]")
        if len(items) > 5:
            print(f"    ... og {len(items) - 5} flere")

def print_customers_summary(customers):
    """Print summary of customers."""
    print(f"\n📊 CUSTOMERS SUMMARY ({len(customers)} total)")
    print("=" * 60)
    
    for c in customers[:20]:  # Show first 20
        name = c.get("lastName") or c.get("displayName") or "?"
        first = c.get("firstName") or ""
        cust_id = c.get("id", "?")
        is_company = c.get("isCompany", False)
        
        address = c.get("address", {}) or {}
        city = address.get("city", "")
        
        type_icon = "🏢" if is_company else "👤"
        full_name = f"{first} {name}".strip() if first else name
        
        print(f"  {type_icon} {full_name} - {city} [ID: {cust_id}]")
    
    if len(customers) > 20:
        print(f"  ... og {len(customers) - 20} flere kunder")

def main():
    print("=" * 60)
    print("  SUSOFT DATA SYNC - Lampeland Bakeri")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    # Authenticate
    token = get_auth_token()
    if not token:
        print("\n❌ Could not authenticate. Check credentials.")
        sys.exit(1)
    
    # Fetch products
    products = fetch_products(token)
    if products:
        save_to_json(products, "susoft_products.json")
        print_products_summary(products)
    
    # Fetch customers
    customers = fetch_customers(token)
    if customers:
        save_to_json(customers, "susoft_customers.json")
        print_customers_summary(customers)
    
    print("\n" + "=" * 60)
    print(f"  ✅ SYNC COMPLETE")
    print(f"  Products: {len(products)}")
    print(f"  Customers: {len(customers)}")
    print("=" * 60)

if __name__ == "__main__":
    main()
