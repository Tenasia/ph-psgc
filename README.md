# ph-psgc

Every Philippine region, province, city/municipality and barangay from the **official PSA
Philippine Standard Geographic Code (PSGC)**, as small JSON files you can load straight
from a CDN. A map point for each barangay is included, for apps that show a map.

**Current version: `2026-Q2`.** This is PSA's 2Q 2026 release, as of 30 June 2026:
18 regions, 82 provinces, 149 cities, 1,493 municipalities and 42,010 barangays.
See [CHANGELOG.md](CHANGELOG.md) for what changed in each release.

## Use it

Load the files from jsDelivr. Pin the version tag, so a later update never changes your app
without you knowing:

```
https://cdn.jsdelivr.net/gh/Tenasia/ph-psgc@2026-Q2/psgc/index.json
https://cdn.jsdelivr.net/gh/Tenasia/ph-psgc@2026-Q2/psgc/areas/1381300000.json
https://cdn.jsdelivr.net/gh/Tenasia/ph-psgc@2026-Q2/psgc/points/1381300000.json
```

```js
const BASE = "https://cdn.jsdelivr.net/gh/Tenasia/ph-psgc@2026-Q2/psgc";

// 1. Regions, with their provinces and independent cities.
const index = await fetch(`${BASE}/index.json`).then((r) => r.json());

// 2. One province or independent city: its cities/municipalities and their barangays.
const qc = await fetch(`${BASE}/areas/1381300000.json`).then((r) => r.json());
const barangays = qc.cities[0].barangays; // [["1381300001", "Alicia"], ...]
```

To keep a copy inside your own project instead, download the `psgc/` folder from the
[release](https://github.com/Tenasia/ph-psgc/releases), or run
`git clone --branch 2026-Q2 https://github.com/Tenasia/ph-psgc.git`.

## Files

All codes are PSA's **10-digit** PSGC codes, as text: keep them as strings so the leading
zeros stay.

| File | What it holds |
| :--- | :--- |
| `psgc/index.json` | `regions[]`, each `{code, name, provinces[], independent[]}`. `provinces` are `{code, name}` (BARMM's Special Geographic Area is listed here too). `independent` are cities and municipalities that belong to no province (all of NCR, and highly urbanized/independent cities), as `{code, name, type}`. |
| `psgc/areas/<code>.json` | One file per province **or** independent city (118 files): `{code, name, kind: "province" \| "independent_city", cities[]}`. Each city is `{code, name, type: "city" \| "municipality", barangays}`, and each barangay is `[code, name]`. City of Manila's barangays add a third item, their district, e.g. `["1380601001", "Barangay 1", "Tondo I/II"]`. |
| `psgc/points/index.json` | The bounding box of every area, as `[minLat, minLng, maxLat, maxLng]`, to find which area files are near a GPS position. |
| `psgc/points/<code>.json` | Map points, grouped like `areas/`: `{"c": {cityCode: [lat, lng]}, "b": {barangayCode: [lat, lng]}}`. Each point is inside the place, not just near it. 96% of barangays have their own point. The rest (all of City of Manila's, and newer barangays) are missing from `b`, so fall back to their city's point in `c`. |
| `psgc/search.json` | A compact index of every city/municipality and barangay, for type-ahead search. Its layout is described in the comments of `scripts/build_psgc.py`. |

**Which area file holds a place?** Its province's code, or for NCR and independent cities,
the city's own code. A barangay in Quezon City is in `areas/1381300000.json`; one in
Antipolo City is in `areas/0405800000.json` (Rizal).

**Good to know**
- Since 3Q 2023, the 10 EMBO barangays (Cembo, South Cembo, Comembo, East Rembo,
  West Rembo, Pembo, Pitogo, Rizal, Post Proper Northside and Southside) are under the
  **City of Taguig**, not Makati.
- The Negros Island Region (Region XVIII, 2024) and Sulu (Region IX, out of BARMM in 2024)
  use their new codes.
- When PSA merges a barangay, its code is retired. Records you saved earlier keep the old
  code, so look it up in the release they were saved under.

## Updating to a new PSA release (each quarter)

PSA publishes a new datafile about two weeks after each quarter ends.

1. Download the **PSGC Publication Datafile** (.xlsx) from
   https://psa.gov.ph/classification/psgc in a browser. The site blocks scripts.
2. `python3 scripts/build_psgc.py path/to/PSGC-xQ-YYYY-Publication-Datafile.xlsx`
   rewrites `psgc/` and prints totals. Compare them with PSA's summary.
3. Rebuild the map points with `python3 scripts/build_points.py path/to/philippines-json-maps`.
   The script's header explains how to download the boundaries.
4. Add the release to `CHANGELOG.md`, commit, and tag it: `git tag 2026-Q3 && git push --tags`.

Both scripts use only the Python standard library.

## Credits and licences

- **This repository** (the build scripts and the way the files are put together): MIT licence,
  see [LICENSE](LICENSE). The data inside keeps its own terms, below.
- **PSGC codes and names:** Philippine Statistics Authority (PSA),
  [Philippine Standard Geographic Code](https://psa.gov.ph/classification/psgc). PSA's
  condition of use is to **credit PSA as the source** wherever you show this data.
- **Map points:** computed from the barangay boundaries in
  [faeldon/philippines-json-maps](https://github.com/faeldon/philippines-json-maps)
  (built from PSA/NAMRIA shapefiles, PSGC 4Q 2023), MIT licence. See
  [licenses/philippines-json-maps-MIT.txt](licenses/philippines-json-maps-MIT.txt). Keep that
  notice with any copy of `psgc/points/`.
