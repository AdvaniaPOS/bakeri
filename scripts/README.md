# Scripts

Konsoliderte CLI-skripter for setup, import og migrasjon.

## Brukere

```powershell
# Demo-bruker (idempotent)
& ".venv\Scripts\python.exe" -m scripts.create_user --demo

# Egendefinert bruker
& ".venv\Scripts\python.exe" -m scripts.create_user `
    --email jon@easify.no --password "hemmelig" `
    --first-name Jon --last-name Bakeri `
    --tenant-slug jonb --tenant-name "Lampeland Bakeri"
```

## Import av data

```powershell
# Kunder fra SuSoft-eksport (data/susoft_customers.json eller _full)
& ".venv\Scripts\python.exe" -m scripts.import_data customers --tenant-slug jonb

# Produkter fra SuSoft (data/susoft_products.json)
& ".venv\Scripts\python.exe" -m scripts.import_data products --tenant-slug jonb --source susoft

# Egne bakeri-produkter (data/bakeri_produkter.json)
& ".venv\Scripts\python.exe" -m scripts.import_data products --tenant-slug jonb --source bakery
```

Bruk `--wipe` for å tømme eksisterende rader for tenant før import.

## Migrasjoner

```powershell
# Kjør alle pending migrasjoner i riktig rekkefølge (idempotent)
& ".venv\Scripts\python.exe" -m scripts.migrate
```
