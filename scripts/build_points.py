#!/usr/bin/env python3
"""
Build the map points used by the location pin: one point inside every barangay, plus
one per city/municipality, so the map can fly to whatever place the respondent picked.

Usage:
    python3 scripts/build_points.py path/to/philippines-json-maps

Get the boundaries (MIT licence, built from PSA/NAMRIA shapefiles) with:
    git clone --depth 1 --filter=blob:none --sparse https://github.com/faeldon/philippines-json-maps.git
    cd philippines-json-maps && git sparse-checkout set 2023/geojson/municities/lowres 2023/geojson/provdists/lowres

Run it after build_psgc.py: places are grouped like psgc/areas/. Barangays the
boundaries don't have (newer ones, and all of Manila's, which are only drawn as one city)
fall back to their city's point.

Output (served as static files by Vercel):
    psgc/points/index.json    bounding box of every area, to find the areas near a GPS fix
    psgc/points/<code>.json   per area: {"c": {city: [lat, lng]}, "b": {barangay: [lat, lng]}}

Only the Python standard library is used.
"""

import json
import shutil
import sys
from pathlib import Path

PSGC_DIR = Path(__file__).resolve().parents[1] / "psgc"
OUT_DIR = PSGC_DIR / "points"
BARANGAY_BOUNDARIES = "2023/geojson/municities/lowres"
CITY_BOUNDARIES = "2023/geojson/provdists/lowres"
DECIMALS = 5  # about 1 m

# Places PSA re-coded after the boundaries were drawn (same land, new region code):
# new code prefix -> prefix in the 2023 boundaries. The rest of the code is unchanged.
RECODED = {
    "18045": "06045",  # Negros Occidental -> Negros Island Region (2024)
    "18046": "07046",  # Negros Oriental -> Negros Island Region
    "18061": "07061",  # Siquijor -> Negros Island Region
    "18302": "06302",  # City of Bacolod -> Negros Island Region
    "09066": "19066",  # Sulu, out of BARMM (2024)
}


def boundary_code(code: str) -> str:
    old = RECODED.get(code[:5])
    return old + code[5:] if old else code


def ring_area_centroid(ring):
    """Signed area and centroid of a closed [lng, lat] ring (shoelace formula)."""
    a = cx = cy = 0.0
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        cross = x1 * y2 - x2 * y1
        a += cross
        cx += (x1 + x2) * cross
        cy += (y1 + y2) * cross
    a /= 2
    if a == 0:
        xs, ys = zip(*ring)
        return 0.0, (sum(xs) / len(xs), sum(ys) / len(ys))
    return a, (cx / (6 * a), cy / (6 * a))


def inside(x, y, ring):
    hit = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            hit = not hit
    return hit


def point_in_polygon(polygon):
    """A point inside the polygon: its centroid, or (for odd shapes) the middle of the
    widest horizontal span through the centroid's latitude."""
    outer = [tuple(p[:2]) for p in polygon[0]]
    _, (x, y) = ring_area_centroid(outer)
    holes = [[tuple(p[:2]) for p in r] for r in polygon[1:]]
    if inside(x, y, outer) and not any(inside(x, y, h) for h in holes):
        return x, y
    xs = []
    for ring in [outer, *holes]:
        for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
            if (y1 > y) != (y2 > y):
                xs.append((x2 - x1) * (y - y1) / (y2 - y1) + x1)
    xs.sort()
    spans = [(b - a, (a + b) / 2) for a, b in zip(xs[::2], xs[1::2])]
    return (max(spans)[1], y) if spans else (x, y)


def feature_point(geometry):
    """Point inside the largest part of a (multi)polygon and the total area, or None."""
    polygons = geometry["coordinates"] if geometry["type"] == "MultiPolygon" else [geometry["coordinates"]]
    sized = [(abs(ring_area_centroid([tuple(p[:2]) for p in poly[0]])[0]), poly) for poly in polygons if poly and poly[0]]
    if not sized:
        return None
    _, largest = max(sized, key=lambda s: s[0])
    return point_in_polygon(largest), sum(s[0] for s in sized)


def latlng(x, y):
    return [round(y, DECIMALS), round(x, DECIMALS)]


def read_points(folder: Path, code_key: str):
    """Code -> (lng, lat, area) for every feature in a folder of GeoJSON files."""
    files = sorted(folder.glob("*.json"))
    if not files:
        sys.exit(f"No boundary files found in {folder}")
    points = {}
    for f in files:
        # A place with no parts is written as an empty GeometryCollection.
        for feature in json.loads(f.read_text(encoding="utf-8")).get("features", []):
            code = str(feature["properties"].get(code_key) or "").zfill(10)
            placed = feature_point(feature["geometry"]) if feature.get("geometry") and code.strip("0") else None
            if placed:
                (x, y), area = placed
                points[code] = (x, y, area)
    return points


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    found = read_points(Path(sys.argv[1]) / BARANGAY_BOUNDARIES, "adm4_psgc")
    city_shapes = read_points(Path(sys.argv[1]) / CITY_BOUNDARIES, "adm3_psgc")

    shutil.rmtree(OUT_DIR, ignore_errors=True)
    OUT_DIR.mkdir(parents=True)
    index, total, missing = {}, 0, 0

    for area_file in sorted((PSGC_DIR / "areas").glob("*.json")):
        area = json.loads(area_file.read_text(encoding="utf-8"))
        cities, barangays = {}, {}
        for city in area["cities"]:
            known = [found[boundary_code(b[0])] for b in city["barangays"] if boundary_code(b[0]) in found]
            if known:
                # Area-weighted middle of its barangays, snapped to the nearest one so it
                # never lands in the sea between islands.
                weight = sum(k[2] for k in known) or len(known)
                mx = sum(k[0] * (k[2] or 1) for k in known) / weight
                my = sum(k[1] * (k[2] or 1) for k in known) / weight
                near = min(known, key=lambda k: (k[0] - mx) ** 2 + (k[1] - my) ** 2)
                cities[city["code"]] = latlng(near[0], near[1])
            elif boundary_code(city["code"]) in city_shapes:
                cities[city["code"]] = latlng(*city_shapes[boundary_code(city["code"])][:2])
            for b in city["barangays"]:
                total += 1
                old = boundary_code(b[0])
                if old in found:
                    barangays[b[0]] = latlng(found[old][0], found[old][1])
                else:
                    missing += 1

        points = list(cities.values()) + list(barangays.values())
        if not points:
            continue
        lats, lngs = [p[0] for p in points], [p[1] for p in points]
        index[area["code"]] = [min(lats), min(lngs), max(lats), max(lngs)]
        (OUT_DIR / area_file.name).write_text(
            json.dumps({"c": cities, "b": barangays}, separators=(",", ":")), encoding="utf-8"
        )

    (OUT_DIR / "index.json").write_text(
        json.dumps(
            {
                "source": "PSA/NAMRIA boundaries via github.com/faeldon/philippines-json-maps (PSGC 4Q 2023, MIT)",
                "areas": index,
            },
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    print(f"{len(index)} areas, {total - missing:,} of {total:,} barangays placed ({missing:,} use their city's point)")
    unplaced = sum(len(json.loads(f.read_text())["cities"]) for f in (PSGC_DIR / "areas").glob("*.json")) - sum(
        len(json.loads(f.read_text())["c"]) for f in OUT_DIR.glob("*.json") if f.name != "index.json"
    )
    if unplaced:
        print(f"{unplaced} cities/municipalities have no point; the map opens on their province instead")


if __name__ == "__main__":
    main()
