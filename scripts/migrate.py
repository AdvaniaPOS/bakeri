#!/usr/bin/env python3
"""
Kjør alle pending DB-migrasjoner i riktig rekkefølge.

Hver `migrate_*.py` i prosjektroten er idempotent og trygg å re-kjøre.
Denne wrapperen samler dem og dokumenterer rekkefølgen.
"""
from __future__ import annotations

import importlib
import sys
import traceback

MIGRATIONS = [
    "migrate_schema",            # Legger til nye kolonner (SuSoft-felt, faktura-tracking)
    "migrate_lead_days",         # Oppdaterer CHECK-constraint på order_lead_days
    "migrate_unique_constraints",  # Tenant-scoped unike indekser
]


def main(argv: list[str] | None = None) -> int:
    print(f"🔧 Kjører {len(MIGRATIONS)} migrasjon(er)...\n")
    failed: list[str] = []

    for name in MIGRATIONS:
        print(f"── {name} " + "─" * (60 - len(name)))
        try:
            mod = importlib.import_module(name)
            run = getattr(mod, "main", None) or getattr(mod, "run", None)
            if callable(run):
                run()
            else:
                # Fallback: import-tidspunktets sideeffekt har allerede kjørt.
                print(f"   (ingen main()/run() — antar kjørt ved import)")
        except SystemExit as e:
            if e.code:
                failed.append(name)
                print(f"   ❌ {name} avsluttet med kode {e.code}")
        except Exception:
            failed.append(name)
            traceback.print_exc()
        print()

    if failed:
        print(f"❌ Feilet: {', '.join(failed)}")
        return 1
    print("✅ Alle migrasjoner gjennomført.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
