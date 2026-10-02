#!/usr/bin/env python3
"""
Build the location data used by the PSGC picker from an official PSA datafile.

Usage:
    python3 scripts/build_psgc.py path/to/PSGC-Publication-Datafile.xlsx

Download the latest "PSGC Publication Datafile" (.xlsx) in a browser from
https://psa.gov.ph/classification/psgc (updated quarterly), then run this script.
It rewrites psgc/ (except points/, which build_points.py makes) and prints a summary to compare against PSA's own totals.

Output (served as static files by Vercel):
    psgc/index.json          regions, each with its provinces and independent cities
    psgc/areas/<code>.json   one per province / independent city: its cities and
                                    municipalities, each with its barangays
    psgc/search.json         compact index for the location search box

Only the Python standard library is used (an .xlsx file is zipped XML).
PSA's use condition: acknowledge the Philippine Statistics Authority as the source.
"""

import json
import re
import shutil
import sys
import zipfile
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
OUT_DIR = Path(__file__).resolve().parents[1] / "psgc"

# Placeholder rows PSA lists without a geographic level.
SPECIAL_GEOGRAPHIC_AREA = "Special Geographic Area"


def clean(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "")).strip()


def to_int(value) -> int:
    """Population cells can be blank or '-' for places created after the 2020 census."""
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def sort_key(name: str):
    """'City of Cebu' sorts under C; 'Barangay 2' before 'Barangay 10'."""
    base = re.sub(r"^(City of|Municipality of)\s+", "", name, flags=re.I)
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", base)]


def read_sheet(path: Path, sheet_name: str = "PSGC"):
    z = zipfile.ZipFile(path)
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall(NS + "si"):
            shared.append("".join(t.text or "" for t in si.iter(NS + "t")))

    workbook = ET.fromstring(z.read("xl/workbook.xml"))
    rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
    target = None
    for s in workbook.find(NS + "sheets"):
        if s.get("name", "").strip().upper() == sheet_name:
            target = rels[s.get(REL_NS + "id")]
    if target is None:
        sys.exit(f'No "{sheet_name}" sheet found in {path}')
    target = target.lstrip("/")
    target = target if target.startswith("xl/") else "xl/" + target

    header = None
    for row in ET.fromstring(z.read(target)).iter(NS + "row"):
        cells = {}
        for c in row.findall(NS + "c"):
            col = re.match(r"[A-Z]+", c.get("r")).group()
            v = c.find(NS + "v")
            if v is not None:
                cells[col] = shared[int(v.text)] if c.get("t") == "s" else v.text
            else:
                inline = c.find(NS + "is")
                if inline is not None:
                    cells[col] = "".join(t.text or "" for t in inline.iter(NS + "t"))
        if header is None:
            header = {col: clean(val).lower() for col, val in cells.items()}
            continue
        yield {header.get(col, col): val for col, val in cells.items()}


def column(row, *names):
    for key, val in row.items():
        if any(key.startswith(n) for n in names):
            return val
    return None


def publication_date(path: Path) -> str:
    """Read 'Publication date' from the Metadata sheet when present."""
    try:
        for row in read_sheet(path, "METADATA"):
            values = [clean(v) for v in row.values() if v]
            if len(values) >= 2 and values[0].lower().startswith("publication date"):
                return values[1]
    except SystemExit:
        pass
    return "unknown"


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    src = Path(sys.argv[1])

    rows = []
    for r in read_sheet(src):
        code = clean(column(r, "10-digit psgc") or "")
        if not re.fullmatch(r"\d{10}", code):
            continue
        rows.append({
            "code": code,
            "name": clean(column(r, "name") or ""),
            "level": clean(column(r, "geographic level") or ""),
            "city_class": clean(column(r, "city class") or ""),
            "population": to_int(column(r, "2020 population")),
        })

    regions = {r["code"][:2]: r for r in rows if r["level"] == "Reg"}
    provinces = {r["code"][:5]: r for r in rows if r["level"] == "Prov"}
    # BARMM's Special Geographic Area is listed without a level but works like a province.
    for r in rows:
        if not r["level"] and r["name"] == SPECIAL_GEOGRAPHIC_AREA:
            provinces[r["code"][:5]] = r
    lgus = {r["code"][:7]: r for r in rows if r["level"] in ("City", "Mun")}
    sub_municipalities = {r["code"][:7]: r for r in rows if r["level"] == "SubMun"}

    # Barangays belong to a city/municipality by their first 7 digits. The City of
    # Manila's barangays sit under its 14 districts (sub-municipalities) instead.
    barangays = defaultdict(list)
    orphans = []
    for r in rows:
        if r["level"] != "Bgy":
            continue
        parent = r["code"][:7]
        district = None
        if parent in sub_municipalities:
            district = sub_municipalities[parent]["name"]
            parent = next(
                (k for k in lgus if k[:5] == parent[:5] and k[5:7] == "00"),
                None,
            )
        if parent not in lgus:
            orphans.append(r)
            continue
        entry = [r["code"], r["name"]] + ([district] if district else [])
        barangays[parent].append(entry)

    def lgu_entry(key):
        lgu = lgus[key]
        brgys = sorted(barangays.get(key, []), key=lambda b: sort_key(b[1]))
        return {
            "code": lgu["code"],
            "name": lgu["name"],
            "type": "city" if lgu["level"] == "City" else "municipality",
            "barangays": brgys,
        }

    # Group cities/municipalities under provinces; the rest are independent
    # (NCR's cities, highly urbanized cities, and the City of Isabela).
    by_province = defaultdict(list)
    independent = defaultdict(list)
    for key, lgu in lgus.items():
        if lgu["code"][:5] in provinces:
            by_province[lgu["code"][:5]].append(key)
        else:
            independent[lgu["code"][:2]].append(key)

    # Replace only what this script writes; points/ comes from build_points.py.
    if (OUT_DIR / "areas").exists():
        shutil.rmtree(OUT_DIR / "areas")
    (OUT_DIR / "areas").mkdir(parents=True)

    def write(path: Path, data):
        path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    index_regions = []
    for rkey, region in regions.items():  # PSA's own order (NCR, CAR, I, II, …)
        region_provinces = sorted(
            (p for pkey, p in provinces.items() if pkey[:2] == rkey),
            key=lambda p: sort_key(p["name"]),
        )
        region_independent = sorted(
            (lgus[k] for k in independent.get(rkey, [])),
            key=lambda c: sort_key(c["name"]),
        )
        for p in region_provinces:
            keys = sorted(by_province[p["code"][:5]], key=lambda k: sort_key(lgus[k]["name"]))
            write(OUT_DIR / "areas" / f'{p["code"]}.json', {
                "code": p["code"], "name": p["name"], "kind": "province",
                "cities": [lgu_entry(k) for k in keys],
            })
        for c in region_independent:
            write(OUT_DIR / "areas" / f'{c["code"]}.json', {
                "code": c["code"], "name": c["name"], "kind": "independent_city",
                "cities": [lgu_entry(c["code"][:7])],
            })
        index_regions.append({
            "code": region["code"],
            "name": region["name"],
            "provinces": [{"code": p["code"], "name": p["name"]} for p in region_provinces],
            "independent": [
                {"code": c["code"], "name": c["name"],
                 "type": "city" if c["level"] == "City" else "municipality"}
                for c in region_independent
            ],
        })

    # Compact search index for the "type your location" box (loaded on demand).
    #   regions: [code, name]
    #   areas:   [code, name, regionIndex, isIndependentCity]   (provinces + independent cities)
    #   cities:  [code, name, areaIndex, population2020, [[barangayName, codeOffset(, district)], ...]]
    # A barangay's full code is the city's code + codeOffset.
    search_regions, search_areas, search_cities = [], [], []
    area_index = {}
    for ri, reg in enumerate(index_regions):
        search_regions.append([reg["code"], reg["name"]])
        for p in reg["provinces"]:
            area_index[p["code"]] = len(search_areas)
            search_areas.append([p["code"], p["name"], ri, 0])
        for c in reg["independent"]:
            area_index[c["code"]] = len(search_areas)
            search_areas.append([c["code"], c["name"], ri, 1])
    for key, lgu in sorted(lgus.items()):
        area_code = (lgu["code"][:5] + "00000") if lgu["code"][:5] in provinces else lgu["code"]
        base = int(lgu["code"])
        brgys = [
            [b[1], int(b[0]) - base] + ([b[2]] if len(b) > 2 else [])
            for b in sorted(barangays.get(key, []), key=lambda b: sort_key(b[1]))
        ]
        search_cities.append([lgu["code"], lgu["name"], area_index[area_code], lgu["population"], brgys])
    write(OUT_DIR / "search.json", {
        "published": publication_date(src),
        "regions": search_regions,
        "areas": search_areas,
        "cities": search_cities,
    })

    published = publication_date(src)
    write(OUT_DIR / "index.json", {
        "source": "Philippine Statistics Authority (PSA), Philippine Standard Geographic Code",
        "source_url": "https://psa.gov.ph/classification/psgc",
        "published": published,
        "regions": index_regions,
    })

    total_bgy = sum(len(v) for v in barangays.values())
    print(f"PSGC data published {published}")
    print(f"  regions:              {len(regions)}")
    print(f"  provinces:            {sum(1 for p in provinces.values() if p['level'] == 'Prov')}"
          f" (+ special areas: {sum(1 for p in provinces.values() if p['level'] != 'Prov')})")
    print(f"  cities:               {sum(1 for l in lgus.values() if l['level'] == 'City')}")
    print(f"  municipalities:       {sum(1 for l in lgus.values() if l['level'] == 'Mun')}")
    print(f"  barangays:            {total_bgy}")
    print(f"  independent LGUs:     {sum(len(v) for v in independent.values())}")
    print(f"  area files written:   {len(list((OUT_DIR / 'areas').glob('*.json')))}")
    if orphans:
        sys.exit(f"ERROR: {len(orphans)} barangays have no city/municipality, e.g. {orphans[:3]}")


if __name__ == "__main__":
    main()
