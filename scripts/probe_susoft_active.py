"""
Undersøk Susoft-produkt-API for å finne ut hvilket felt som faktisk
indikerer "aktiv/inaktiv" slik det vises i Susoft-UI.

Kjører tre kall:
  1. /product/search activityFlag=ACTIVE
  2. /product/search activityFlag=INACTIVE
  3. /product/search activityFlag=ALL
og dumper de første få produktenes nøkler + active/webshopAllowed/etc.

Bruk:
  python -m scripts.probe_susoft_active --tenant-id 1
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List

from app.database import SessionLocal
from app.services.susoft import SuSoftService


def _fetch(svc: SuSoftService, flag: str, page_size: int = 200) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    page = 0
    while True:
        endpoint = f"/product/search?page={page}&pageSize={page_size}&activityFlag={flag}"
        resp = svc._request_with_throttle_retry(
            "POST", endpoint, json={"filterGroups": []}, headers=svc._get_headers()
        )
        if not resp.is_success:
            print(f"  HTTP {resp.status_code} på {endpoint}: {resp.text[:200]}")
            break
        batch = resp.json() or []
        if not isinstance(batch, list):
            print(f"  Uventet svar: {type(batch)}")
            break
        items.extend(batch)
        if len(batch) < page_size:
            break
        page += 1
    return items


_INTERESTING_KEYS = (
    "id", "name", "active", "isActive", "deleted", "isDeleted",
    "webshopAllowed", "visible", "isVisible", "abcCode",
    "stockLevel", "stockQuantity", "discontinued",
)


def _summarize(label: str, items: List[Dict[str, Any]]) -> None:
    print(f"\n--- {label}: {len(items)} produkter ---")
    if not items:
        return
    sample = items[0]
    print(f"Alle nøkler i første produkt: {sorted(sample.keys())}")
    print("\nFelt-verdier (første 5 produkter):")
    for p in items[:5]:
        slim = {k: p.get(k) for k in _INTERESTING_KEYS if k in p}
        print(f"  {json.dumps(slim, ensure_ascii=False)}")

    # Tell hvor mange som har hvert flagg = false
    counts = {}
    for k in ("active", "isActive", "deleted", "isDeleted", "webshopAllowed", "visible", "isVisible", "discontinued"):
        false_count = sum(1 for p in items if p.get(k) is False)
        true_count = sum(1 for p in items if p.get(k) is True)
        none_count = sum(1 for p in items if p.get(k) is None)
        if true_count + false_count + none_count > 0:
            counts[k] = f"true={true_count} false={false_count} null={none_count}"
    print(f"\nFlagg-fordeling: {json.dumps(counts, indent=2)}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant-id", type=int, required=True)
    args = parser.parse_args()

    db = SessionLocal()
    try:
        svc = SuSoftService(db, tenant_id=args.tenant_id)

        for flag in ("ACTIVE", "INACTIVE", "ALL"):
            print(f"\n========== activityFlag={flag} ==========")
            items = _fetch(svc, flag)
            _summarize(flag, items)

        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
