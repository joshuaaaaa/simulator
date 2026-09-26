"""Sestaví podklady mapy FS25 Lednice z reálných dat (Overture Maps / OSM + DEM).

Výstup (složka FS25_Lednice/):
  maps/data/dem.png                 výškopis 16 bit, 1 m/px
  maps/data/*_weight.png            texturové masky terénu (asfalt, štěrk, tráva, les, pole ...)
  maps/data/infoLayer_farmlands.png pozemky k nákupu
  maps/config/farmlands.xml
  maps/overview.dds + icon          mapa v PDA a ikona módu
  modDesc.xml, maps/map.xml
  import/*.i3d                      budovy, silnice (spline), pole, vodní hladiny
  import/trees.csv                  pozice stromů (Lua skript pro Giants Editor je v ge_scripts/)
"""
import hashlib
import json
import math
import shutil
import sys
import time
from pathlib import Path

import numpy as np
import shapely
from PIL import Image, ImageDraw
from scipy import ndimage
from shapely.geometry import Polygon
from shapely.geometry.polygon import orient

sys.path.insert(0, str(Path(__file__).parent))
import config as C  # noqa: E402
from geo import Canvas, HALF, MAP_BOX, iter_polys, load, name_of, RAW  # noqa: E402
from i3d import I3D, Mesh  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MOD = ROOT / "FS25_Lednice"
DATA = MOD / "maps" / "data"
IMPORT = MOD / "import"
HEIGHT_SCALE = 255.0

T0 = time.time()


def log(msg):
    print(f"[{time.time() - T0:6.1f} s] {msg}", flush=True)


def surface_of(props):
    s = props.get("road_surface")
    return s[0]["value"] if s else None


def is_bridge(props):
    return bool(props.get("road_flags")) and any("is_bridge" in r.get("values", []) for r in props["road_flags"])


# --------------------------------------------------------------------------------------
# 1) Načtení a roztřídění dat
# --------------------------------------------------------------------------------------
ROAD_WIDTH = {"motorway": 10, "trunk": 9, "primary": 8, "secondary": 7, "tertiary": 6.5,
              "unclassified": 5, "residential": 5, "living_street": 4.5, "service": 3.5,
              "track": 3.2, "footway": 2, "path": 1.8, "steps": 2, "cycleway": 2.5,
              "pedestrian": 4, "bridleway": 2, "unknown": 3}
MAJOR = {"motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential",
         "living_street", "service", "unknown"}


def road_texture(cls, surf):
    unpaved = surf in ("unpaved", "gravel", "dirt", "ground", "grass", "compacted", "fine_gravel")
    if cls in ("footway", "path", "steps", "cycleway", "bridleway", "pedestrian"):
        return "concrete" if surf in ("paving_stones", "paved", "concrete", "asphalt") else "gravel"
    if cls == "track":
        return "asphalt" if surf == "paved" else ("gravel" if surf == "gravel" else "mudTracks")
    if cls == "service":
        return "concrete" if surf == "paving_stones" else ("gravel" if unpaved else "asphalt")
    return "gravel" if unpaved else "asphalt"


def collect():
    log("načítám data")
    D = {k: [] for k in ["water_poly", "water_line", "forest", "scrub", "wetland", "farmland", "meadow",
                         "vineyard", "orchard", "park", "garden", "paved_area", "pitch", "cemetery",
                         "roads", "rails", "buildings", "tree_points", "tree_rows", "grass"]}
    for g, p in load("water"):
        st = p.get("subtype")
        if st == "human_made":
            if g.geom_type != "Point":
                D["paved_area"].append(g)
            continue
        if g.geom_type in ("Polygon", "MultiPolygon"):
            D["water_poly"].append((g, name_of(p)))
        elif g.geom_type in ("LineString", "MultiLineString"):
            w = {"river": 14, "canal": 6, "stream": 3}.get(p.get("class"), 3)
            D["water_line"].append(g.buffer(w / 2))
    for g, p in load("land"):
        c = p.get("class")
        if c in ("forest", "wood") and g.area > 0:
            D["forest"].append(g)
        elif c == "scrub":
            D["scrub"].append(g)
        elif c == "wetland":
            D["wetland"].append(g)
        elif c in ("grassland", "grass") and g.area > 0:
            D["grass"].append(g)
        elif c == "tree" and g.geom_type == "Point":
            D["tree_points"].append(g)
        elif c == "tree_row":
            D["tree_rows"].append(g)
    for g, p in load("land_use"):
        c = p.get("class")
        if g.geom_type not in ("Polygon", "MultiPolygon"):
            continue
        key = {"farmland": "farmland", "meadow": "meadow", "vineyard": "vineyard", "orchard": "orchard",
               "park": "park", "garden": "garden", "flowerbed": "garden", "grass": "grass",
               "pitch": "pitch", "plaza": "paved_area", "cemetery": "cemetery"}.get(c)
        if key:
            D[key].append((g, name_of(p)) if key in ("farmland", "meadow", "vineyard", "orchard") else g)
    for g, p in load("infrastructure"):
        if p.get("class") == "parking" and g.geom_type in ("Polygon", "MultiPolygon"):
            D["paved_area"].append(g)
    for g, p in load("segments"):
        if p.get("subtype") == "rail":
            D["rails"].append(g)
        elif p.get("subtype") == "road":
            cls = p.get("class") or "unknown"
            D["roads"].append((g, cls, surface_of(p), is_bridge(p), name_of(p)))
    for g, p in load("buildings"):
        if p.get("is_underground") or g.geom_type not in ("Polygon", "MultiPolygon"):
            continue
        D["buildings"].append((g, p))
    log(", ".join(f"{k}: {len(v)}" for k, v in D.items()))
    return D


# --------------------------------------------------------------------------------------
# 2) Výškopis
# --------------------------------------------------------------------------------------
def build_terrain(D):
    log("výškopis: převzorkování DEM na 1 m")
    z = np.load(RAW / "dem_mosaic.npz")
    H, zoom, tx0, ty0 = z["height"], int(z["z"]), int(z["tx0"]), int(z["ty0"])
    n = C.DEM_SIZE
    # projekci stačí počítat na hrubé mřížce a interpolovat (je hladká)
    step = 32
    coarse = np.arange(0, n + step, step)
    gx, gz = np.meshgrid(coarse - HALF, coarse - HALF)
    lon, lat = C.map_to_lonlat(gx.ravel(), gz.ravel())
    lon, lat = np.asarray(lon).reshape(gx.shape), np.asarray(lat).reshape(gx.shape)
    tpx = ((lon + 180) / 360 * 2 ** zoom - tx0) * 256
    tpy = ((1 - np.arcsinh(np.tan(np.radians(lat))) / math.pi) / 2 * 2 ** zoom - ty0) * 256
    fine = np.arange(n) / step
    ii, jj = np.meshgrid(fine, fine)
    px = ndimage.map_coordinates(tpx, [jj, ii], order=1)
    py = ndimage.map_coordinates(tpy, [jj, ii], order=1)
    h = ndimage.map_coordinates(H, [py - 0.5, px - 0.5], order=3, mode="nearest")
    h = ndimage.gaussian_filter(h, 8)

    def mask1m(geoms, buf=0.0):
        cv = Canvas(n)
        cv.ppm = n / (C.MAP_SIZE + 1)
        cv._px = lambda cs: [(x + HALF + 0.5, zz + HALF + 0.5) for x, zz in cs]
        for g in geoms:
            cv.poly(g.buffer(buf) if buf else g, 255, 0)
        return cv.array() > 0

    log("výškopis: srovnání silnic a parcel budov")
    roads = [g.buffer(ROAD_WIDTH.get(c, 3) / 2 + 1.5) for g, c, s, b, _ in D["roads"] if c in MAJOR or c == "track"]
    rmask = mask1m(roads)
    hs = ndimage.gaussian_filter(h, 20)
    rsoft = ndimage.gaussian_filter(rmask.astype(np.float32), 3)
    h = h * (1 - rsoft) + hs * rsoft

    lab = np.zeros((n, n), np.int32)
    cv = Image.new("I", (n, n), 0)
    dr = ImageDraw.Draw(cv)
    for i, (g, _) in enumerate(D["buildings"], 1):
        for p in iter_polys(g.buffer(2.0)):
            dr.polygon([(x + HALF + 0.5, zz + HALF + 0.5) for x, zz in p.exterior.coords], fill=i)
    lab = np.asarray(cv, np.int32)
    ids = np.arange(1, len(D["buildings"]) + 1)
    means = np.asarray(ndimage.mean(h, lab, ids))
    lut = np.concatenate([[0], np.nan_to_num(means)])
    h = np.where(lab > 0, lut[lab], h)
    h = ndimage.gaussian_filter(h, 1.2)

    log("výškopis: vodní plochy a toky")
    water_levels = []
    wmask = np.zeros((n, n), bool)
    for g, name in D["water_poly"]:
        m = mask1m([g])
        if not m.any():
            continue
        # výpočty jen ve výřezu kolem vodní plochy
        ys, xs = np.nonzero(m)
        sl = (slice(max(ys.min() - 8, 0), ys.max() + 9), slice(max(xs.min() - 8, 0), xs.max() + 9))
        mc, hc = m[sl], h[sl]
        ring = ndimage.binary_dilation(mc, iterations=4) & ~mc
        level = float(np.percentile(hc[ring], 10)) - 0.35 if ring.any() else float(hc[mc].min())
        d = ndimage.distance_transform_edt(mc)
        bed = level - np.minimum(3.0, 0.5 + 0.3 * d)
        h[sl] = np.where(mc, np.minimum(hc, bed), hc)
        wmask |= m
        water_levels.append((g, name, level))
    lm = mask1m(D["water_line"])
    d = ndimage.distance_transform_edt(lm)
    h = np.where(lm & ~wmask, h - np.minimum(1.6, 0.5 + 0.4 * d), h)
    # břehy: mírné svahy kolem vody
    h = np.where(wmask | lm, h, ndimage.gaussian_filter(h, 1.0))

    base = math.floor(float(h.min())) - 2.0
    rel = h - base
    dem = np.clip(rel / HEIGHT_SCALE * 65535, 0, 65535).astype(np.uint16)
    DATA.mkdir(parents=True, exist_ok=True)
    Image.fromarray(dem).save(DATA / "dem.png")
    log(f"dem.png {n}x{n}: {h.min():.1f}–{h.max():.1f} m n. m. (0 v mapě = {base:.0f} m n. m.)")
    terrain = dem.astype(np.float32) / 65535 * HEIGHT_SCALE
    return terrain, base, water_levels


def height_at(T, x, z):
    """Bilineární výška terénu v souřadnicích mapy (FS25: y)."""
    scalar = np.ndim(x) == 0
    x = np.clip(np.atleast_1d(np.asarray(x, float)) + HALF, 0, C.MAP_SIZE - 1e-3)
    z = np.clip(np.atleast_1d(np.asarray(z, float)) + HALF, 0, C.MAP_SIZE - 1e-3)
    h = ndimage.map_coordinates(T, [z, x], order=1)
    return h[0] if scalar else h


# --------------------------------------------------------------------------------------
# 3) Texturové masky
# --------------------------------------------------------------------------------------
# pořadí = priorita (pozdější přepisuje dřívější)
LAYERS = ["grass", "grassMeadow", "field", "fieldLight", "forest", "scrub", "wetland", "garden",
          "concrete", "mudTracks", "gravel", "riverMud", "asphalt"]


def build_textures(D):
    log("texturové masky 0,5 m/px")
    S = C.WEIGHT_SIZE
    idx = np.zeros((S, S), np.uint8)

    def paint(key, geoms):
        cv = Canvas(S)
        for g in geoms:
            cv.poly(g, 255, 0)
        idx[cv.array() > 0] = LAYERS.index(key)

    fields = lambda k: [g for g, _ in D[k]]  # noqa: E731
    paint("grassMeadow", fields("meadow") + D["grass"])
    paint("field", fields("farmland"))
    paint("fieldLight", fields("vineyard") + fields("orchard"))
    paint("forest", D["forest"])
    paint("scrub", D["scrub"])
    paint("wetland", D["wetland"])
    paint("garden", D["garden"] + D["cemetery"] + D["pitch"])
    paint("concrete", D["paved_area"])
    by_tex = {}
    for g, cls, surf, bridge, _ in D["roads"]:
        by_tex.setdefault(road_texture(cls, surf), []).append(g.buffer(ROAD_WIDTH.get(cls, 3) / 2))
    paint("mudTracks", by_tex.get("mudTracks", []))
    paint("gravel", by_tex.get("gravel", []) + [g.buffer(2.2) for g in D["rails"]])
    paint("riverMud", [g.buffer(1.5) for g, _ in D["water_poly"]] + D["water_line"])
    paint("concrete", by_tex.get("concrete", []))
    paint("asphalt", by_tex.get("asphalt", []))
    for k, name in enumerate(LAYERS):
        m = (idx == k).astype(np.uint8) * 255
        Image.fromarray(m).save(DATA / f"lednice_{name}_weight.png", optimize=False, compress_level=6)
    log("masky uloženy: " + ", ".join(LAYERS))
    return idx


# --------------------------------------------------------------------------------------
# 4) Pole a pozemky
# --------------------------------------------------------------------------------------
def build_fields(D, T, built_up):
    log("pole a pozemky")
    fields = []
    for kind, crop in (("farmland", "orná půda"), ("meadow", "louka / tráva"),
                       ("vineyard", "vinice (hrozny)"), ("orchard", "sad")):
        for g, name in D[kind]:
            g = g.intersection(MAP_BOX.buffer(-25)).buffer(-2.0).difference(built_up)
            for p in iter_polys(g):
                p = p.simplify(1.0)
                min_area = 5000 if kind == "farmland" else 2500
                if p.area >= min_area and p.geom_type == "Polygon" and not p.is_empty:
                    fields.append({"geom": orient(p, 1.0), "kind": kind, "crop": crop, "name": name})
    fields.sort(key=lambda f: (round(f["geom"].centroid.y / 400), f["geom"].centroid.x))

    doc = I3D("lednice_fields")
    doc.open_group("fields", "    ")
    info = []
    for i, f in enumerate(fields, 1):
        p = f["geom"]
        c = p.representative_point()
        cy = float(height_at(T, c.x, c.y))
        doc.open_group(f"field{i:02d}", "      ", (c.x, 0, c.y))
        doc.open_group("polygonPoints", "        ")
        pts = list(p.exterior.coords)[:-1]
        hs = height_at(T, [q[0] for q in pts], [q[1] for q in pts])
        for k, ((x, z), y) in enumerate(zip(pts, hs), 1):
            doc.leaf_group(f"point{k}", "          ", (x - c.x, y, z - c.y))
        doc.close_group("        ")
        doc.leaf_group("nameIndicator", "        ", (0, cy, 0))
        doc.leaf_group("teleportIndicator", "        ", (0, cy, 0))
        doc.close_group("      ")
        info.append({"id": i, "typ": f["kind"], "doporuceni": f["crop"], "nazev": f["name"],
                     "vymera_ha": round(p.area / 10000, 2), "x": round(c.x, 1), "z": round(c.y, 1)})
    doc.close_group("    ")
    doc.write(IMPORT / "fields.i3d")
    (IMPORT / "fields.json").write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")

    # pozemky (farmlands): pole + 10 m okolí; každý pozemek = jedno pole
    S = C.INFO_SIZE
    cv = Canvas(S)
    for i, f in enumerate(fields, 1):
        cv.poly(f["geom"].buffer(10).difference(built_up), min(i, 255), None)
    Image.fromarray(cv.array()).save(DATA / "infoLayer_farmlands.png")
    cfg = MOD / "maps" / "config"
    cfg.mkdir(parents=True, exist_ok=True)
    lines = ['<?xml version="1.0" encoding="utf-8" standalone="no"?>', "<map>",
             '    <farmlands infoLayer="farmlands" pricePerHa="60000">']
    for i, f in enumerate(fields[:255], 1):
        price = {"farmland": 1.0, "meadow": 0.7, "vineyard": 1.4, "orchard": 1.2}[f["kind"]]
        lines.append(f'        <farmland id="{i}" priceScale="{price}" npcName="FARMER"/>')
    lines += ["    </farmlands>", "</map>", ""]
    (cfg / "farmlands.xml").write_text("\n".join(lines), encoding="utf-8")
    log(f"polí: {len(fields)} (orná {sum(f['kind'] == 'farmland' for f in fields)}, "
        f"louky {sum(f['kind'] == 'meadow' for f in fields)}, vinice {sum(f['kind'] == 'vineyard' for f in fields)}, "
        f"sady {sum(f['kind'] == 'orchard' for f in fields)}), celkem "
        f"{sum(f['geom'].area for f in fields) / 1e4:.0f} ha")
    return fields


# --------------------------------------------------------------------------------------
# 5) Budovy (3D modely z půdorysů)
# --------------------------------------------------------------------------------------
WALLS = [(0.93, 0.91, 0.85), (0.95, 0.89, 0.72), (0.90, 0.80, 0.58), (0.86, 0.86, 0.84),
         (0.93, 0.80, 0.70), (0.82, 0.76, 0.66)]
ROOFS = {"tile": (0.56, 0.23, 0.15), "tile2": (0.44, 0.20, 0.14), "slate": (0.27, 0.29, 0.32),
         "flat": (0.42, 0.42, 0.42), "glass": (0.72, 0.84, 0.86), "metal": (0.55, 0.57, 0.58)}
SPECIAL = {"castle": (0.94, 0.92, 0.86), "minaret": (0.86, 0.70, 0.58), "brick": (0.62, 0.36, 0.27)}

# významné stavby – ručně doplněné výšky (m) podle skutečnosti
LANDMARKS = {
    "zámek Lednice": dict(eave=17, roof="hip", roof_h=6, wall="castle", roof_mat="slate"),
    "Minaret": dict(eave=11, roof="flat", wall="minaret", roof_mat="flat", tower=(62, 3.3)),
    "svatý Jakub Starší": dict(eave=12, roof="gable", roof_h=7, wall="castle", roof_mat="slate", tower=(38, 2.8)),
    "Janův hrad": dict(eave=14, roof="flat", wall="brick", roof_mat="flat"),
    "Zámecký skleník": dict(eave=11, roof="gable", roof_h=3, wall="castle", roof_mat="glass"),
    "Maurská vodárna": dict(eave=10, roof="flat", wall="castle", roof_mat="flat"),
    "Zámecké jízdárny": dict(eave=9, roof="hip", roof_h=5, wall="castle", roof_mat="slate"),
    "Čínský pavilon": dict(eave=5, roof="hip", roof_h=3, wall="castle", roof_mat="tile2"),
    "Lovecký zámeček": dict(eave=10, roof="hip", roof_h=5, wall="castle", roof_mat="tile"),
    "Hubertova šopa": dict(eave=4, roof="gable", roof_h=3, wall="brick", roof_mat="tile2"),
}


def building_params(g, p):
    name = name_of(p)
    for key, v in LANDMARKS.items():
        if key == name:
            return dict(v, name=name)
    cls, sub = p.get("class"), p.get("subtype")
    hsh = int(hashlib.md5(str(p.get("id")).encode()).hexdigest(), 16)
    wall = f"w{hsh % len(WALLS)}"
    area = g.area
    height, floors = p.get("height"), p.get("num_floors")
    if cls in ("garage", "roof"):
        return dict(eave=2.7, roof="flat", wall=wall, roof_mat="flat", name=name)
    if cls == "greenhouse":
        return dict(eave=3.0, roof="gable", roof_h=1.8, wall="glass", roof_mat="glass", name=name)
    if sub in ("industrial", "agricultural") or cls in ("warehouse", "industrial", "barn"):
        eave = height or 6.5
        return dict(eave=eave, roof="gable", roof_h=2.5, wall="w3", roof_mat="metal", name=name)
    if floors:
        eave = floors * 3.0 + 0.6
    elif height:
        eave = max(2.8, height * 0.72)
    elif area < 25:
        eave = 2.6
    elif area > 600:
        eave = 7.5
    else:
        eave = 4.2
    roof_mat = "tile" if hsh % 3 else "tile2"
    kind = "hip" if area > 350 else "gable"
    return dict(eave=eave, roof=kind, roof_h=None, wall=wall, roof_mat=roof_mat, name=name)


def _rect_roof(mesh, mat, rect, y0, rh, hip):
    """Sedlová/valbová střecha na minimálním opsaném obdélníku."""
    r = np.array(rect.exterior.coords[:4])
    l01, l12 = np.linalg.norm(r[1] - r[0]), np.linalg.norm(r[2] - r[1])
    if l01 < l12:
        r = np.roll(r, -1, axis=0)
        l01, l12 = l12, l01
    # r0-r1 je dlouhá strana
    m03, m12 = (r[0] + r[3]) / 2, (r[1] + r[2]) / 2
    axis = (m12 - m03) / max(l01, 1e-6)
    inset = min(l12 / 2, l01 / 2 - 0.2) if hip else 0.0
    ra, rb = m03 + axis * inset, m12 - axis * inset
    P = lambda q, y: (q[0], y, q[1])  # noqa: E731
    ctr = r.mean(axis=0)
    y1 = y0 + rh

    def up(a, b, c):
        n = np.cross(np.subtract(b, a), np.subtract(c, a))
        n = n if n[1] > 0 else -n
        return n
    s1 = [P(r[0], y0), P(r[1], y0), P(rb, y1), P(ra, y1)]
    s2 = [P(r[2], y0), P(r[3], y0), P(ra, y1), P(rb, y1)]
    for s in (s1, s2):
        n = up(*s[:3])
        mesh.quad(mat, *s, want_normal=n)
    e1 = [P(r[1], y0), P(r[2], y0), P(rb, y1)]
    e2 = [P(r[3], y0), P(r[0], y0), P(ra, y1)]
    for tri in (e1, e2):
        mid = np.mean(tri, axis=0)
        mesh.tri(mat, *tri, want_normal=np.array([mid[0] - ctr[0], 0.3 if hip else 0, mid[2] - ctr[1]]))


def _prism(mesh, wall_mat, roof_mat, poly, y0, y1, flat_top=True):
    poly = orient(poly, 1.0)
    rings = [poly.exterior] + list(poly.interiors)
    for ring in rings:
        cs = list(ring.coords)
        for (x0, z0), (x1, z1) in zip(cs[:-1], cs[1:]):
            dx, dz = x1 - x0, z1 - z0
            if dx * dx + dz * dz < 1e-4:
                continue
            outward = np.array([dz, 0, -dx])
            if ring is not poly.exterior:
                outward = -outward
            mesh.quad(wall_mat, (x0, y0, z0), (x1, y0, z1), (x1, y1, z1), (x0, y1, z0), want_normal=outward)
    if flat_top:
        for t in shapely.constrained_delaunay_triangles(poly).geoms:
            a, b, c = list(t.exterior.coords)[:3]
            mesh.tri(roof_mat, (a[0], y1, a[1]), (b[0], y1, b[1]), (c[0], y1, c[1]), want_normal=np.array([0, 1, 0]))


def _tower(mesh, wall_mat, roof_mat, c, r, y0, y1, sides=8):
    ring = Polygon([(c.x + r * math.cos(2 * math.pi * k / sides), c.y + r * math.sin(2 * math.pi * k / sides))
                    for k in range(sides)])
    _prism(mesh, wall_mat, roof_mat, ring, y0, y1)
    top = (c.x, y1 + r * 1.6, c.y)
    cs = list(orient(ring, 1.0).exterior.coords)
    for a, b in zip(cs[:-1], cs[1:]):
        mid = ((a[0] + b[0]) / 2 - c.x, 0.5, (a[1] + b[1]) / 2 - c.y)
        mesh.tri(roof_mat, (a[0], y1, a[1]), (b[0], y1, b[1]), top, want_normal=np.array(mid))


def build_buildings(D, T):
    log("budovy: generuji 3D modely")
    doc = I3D("lednice_buildings")
    mat = {f"w{i}": doc.material(f"wall_{i}", c) for i, c in enumerate(WALLS)}
    mat.update({k: doc.material(f"roof_{k}", c) for k, c in ROOFS.items()})
    mat.update({k: doc.material(f"wall_{k}", c) for k, c in SPECIAL.items()})
    TILE = 512
    tiles = {}
    stats = {"pitched": 0, "flat": 0}
    for g, p in D["buildings"]:
        g = g.intersection(MAP_BOX.buffer(-5))
        for poly in iter_polys(g):
            poly = poly.simplify(0.25)
            if poly.area < 6 or poly.is_empty or poly.geom_type != "Polygon":
                continue
            prm = building_params(poly, p)
            cs = np.array(poly.exterior.coords)
            y0 = float(np.min(height_at(T, cs[:, 0], cs[:, 1]))) - 0.4
            y1 = y0 + 0.4 + prm["eave"]
            c = poly.centroid
            key = (int((c.x + HALF) // TILE), int((c.y + HALF) // TILE))
            mesh = tiles.setdefault(key, Mesh())
            wm, rm = mat[prm["wall"]], mat[prm["roof_mat"]]
            rect = poly.minimum_rotated_rectangle
            rectness = poly.area / max(rect.area, 1e-6)
            pitched = prm["roof"] in ("gable", "hip") and rectness > 0.8 and rect.geom_type == "Polygon"
            _prism(mesh, wm, rm, poly, y0, y1, flat_top=not pitched)
            if pitched:
                r = np.array(rect.exterior.coords[:4])
                short = min(np.linalg.norm(r[1] - r[0]), np.linalg.norm(r[2] - r[1]))
                rh = prm.get("roof_h") or min(0.5 * short, 6.0)
                _rect_roof(mesh, rm, rect, y1, rh, prm["roof"] == "hip")
                stats["pitched"] += 1
            else:
                stats["flat"] += 1
            if prm.get("tower"):
                th, tr = prm["tower"]
                _tower(mesh, wm, mat["slate"] if prm["wall"] != "minaret" else wm, c, tr, y0, y0 + th)
    doc.open_group("lednice_buildings", "    ")
    for (i, j), mesh in sorted(tiles.items()):
        if mesh.empty():
            continue
        off = (i * TILE - HALF + TILE / 2, 0.0, j * TILE - HALF + TILE / 2)
        doc.add_mesh(mesh, f"buildings_{i}_{j}", off, "      ")
    doc.close_group("    ")
    doc.write(IMPORT / "buildings.i3d")
    log(f"budovy: {stats['pitched']} se sedlovou/valbovou střechou, {stats['flat']} s plochou střechou")


# --------------------------------------------------------------------------------------
# 6) Silnice jako spline křivky, vodní hladiny
# --------------------------------------------------------------------------------------
def densify(line, step):
    n = max(2, int(line.length / step) + 1)
    return [line.interpolate(d) for d in np.linspace(0, line.length, n)]


def build_splines(D, T):
    log("silnice: spline křivky")
    doc = I3D("lednice_roads")
    groups = {}
    for g, cls, surf, bridge, name in D["roads"]:
        g = g.intersection(MAP_BOX.buffer(-2))
        lines = [g] if g.geom_type == "LineString" else [x for x in getattr(g, "geoms", []) if x.geom_type == "LineString"]
        for ln in lines:
            if ln.length < 5:
                continue
            groups.setdefault(cls, []).append((ln, name))
    doc.open_group("roadSplines", "    ")
    total = 0
    for cls in sorted(groups):
        doc.open_group(cls, "      ")
        for k, (ln, name) in enumerate(groups[cls], 1):
            pts = densify(ln, 8)
            ys = height_at(T, [q.x for q in pts], [q.y for q in pts]) + 0.05
            doc.add_spline([(q.x, y, q.y) for q, y in zip(pts, ys)], f"{cls}_{k:03d}_{name}".rstrip("_"), "        ")
            total += 1
        doc.close_group("      ")
    doc.close_group("    ")
    doc.write(IMPORT / "roads.i3d")
    log(f"silnice: {total} spline křivek ({', '.join(f'{k} {len(v)}' for k, v in sorted(groups.items()))})")


def build_water(water_levels):
    doc = I3D("lednice_water")
    m = doc.material("water_placeholder", (0.18, 0.32, 0.36), 0.8)
    doc.open_group("waterPlanes", "    ")
    info = []
    for k, (g, name, level) in enumerate(water_levels, 1):
        mesh = Mesh()
        g = g.intersection(MAP_BOX).buffer(1.0)
        c = g.centroid
        for poly in iter_polys(g):
            for t in shapely.constrained_delaunay_triangles(poly.simplify(0.5)).geoms:
                a, b, cc = list(t.exterior.coords)[:3]
                mesh.tri(m, (a[0], level, a[1]), (b[0], level, b[1]), (cc[0], level, cc[1]), want_normal=np.array([0, 1, 0]))
        if not mesh.empty():
            doc.add_mesh(mesh, f"water_{k:02d}_{name}".rstrip("_"), (c.x, 0, c.y), "      ",
                         'castsShadows="false" receiveShadows="true"')
            info.append({"nazev": name, "hladina_y": round(level, 2), "plocha_ha": round(g.area / 1e4, 2)})
    doc.close_group("    ")
    doc.write(IMPORT / "water.i3d")
    log(f"vodní plochy: {len(info)}")


# --------------------------------------------------------------------------------------
# 7) Stromy
# --------------------------------------------------------------------------------------
def build_trees(D, T, idx):
    log("stromy")
    rng = np.random.default_rng(42)
    ppm = C.WEIGHT_SIZE / C.MAP_SIZE
    blocked = {LAYERS.index(k) for k in ("asphalt", "gravel", "concrete", "mudTracks", "riverMud", "field",
                                         "fieldLight")}
    out = []

    def ok(x, z):
        u, v = int((x + HALF) * ppm), int((z + HALF) * ppm)
        return 0 <= u < C.WEIGHT_SIZE and 0 <= v < C.WEIGHT_SIZE and idx[v, u] not in blocked

    def scatter(geoms, spacing, kind):
        for g in geoms:
            for p in iter_polys(g.intersection(MAP_BOX.buffer(-10))):
                x0, z0, x1, z1 = p.bounds
                xs = np.arange(x0, x1, spacing)
                zs = np.arange(z0, z1, spacing)
                if not len(xs) or not len(zs):
                    continue
                gx, gz = np.meshgrid(xs, zs)
                gx = gx.ravel() + rng.uniform(-0.4, 0.4, gx.size) * spacing
                gz = gz.ravel() + rng.uniform(-0.4, 0.4, gz.size) * spacing
                inside = shapely.contains_xy(p, gx, gz)
                for x, z in zip(gx[inside], gz[inside]):
                    if ok(x, z):
                        out.append((x, z, kind))

    scatter(D["forest"], 9.0, "forest")
    scatter(D["scrub"], 7.0, "bush")
    # zámecký park: rozptýlené solitérní stromy mimo cesty, vodu a louky
    scatter(D["park"], 22.0, "park")
    for ln in D["tree_rows"]:
        for q in densify(ln, 9):
            if ok(q.x, q.y):
                out.append((q.x, q.y, "alley"))
    for pt in D["tree_points"]:
        if ok(pt.x, pt.y):
            out.append((pt.x, pt.y, "solitary"))
    ys = height_at(T, [t[0] for t in out], [t[1] for t in out]) if out else []
    with open(IMPORT / "trees.csv", "w", encoding="utf-8") as f:
        f.write("x;y;z;rotY;scale;kind\n")
        for (x, z, kind), y in zip(out, ys):
            f.write(f"{x:.2f};{y:.2f};{z:.2f};{rng.uniform(0, 360):.0f};{rng.uniform(0.8, 1.2):.2f};{kind}\n")
    log(f"stromy: {len(out)} pozic")
    return out


# --------------------------------------------------------------------------------------
# 8) Přehledová mapa, ikona, soubory módu
# --------------------------------------------------------------------------------------
COLORS = {"grass": (148, 176, 96), "grassMeadow": (170, 190, 105), "field": (158, 128, 88),
          "fieldLight": (176, 160, 104), "forest": (62, 96, 52), "scrub": (110, 140, 76),
          "wetland": (110, 140, 120), "garden": (130, 170, 90), "concrete": (190, 188, 182),
          "mudTracks": (150, 130, 100), "gravel": (205, 196, 170), "riverMud": (90, 120, 140),
          "asphalt": (90, 90, 94)}


def build_overview(D, idx, fields, trees):
    log("přehledová mapa")
    S = 4096
    step = C.WEIGHT_SIZE // S
    pal = np.array([COLORS[k] for k in LAYERS], np.uint8)
    img = Image.fromarray(pal[idx[::step, ::step]])
    cv = Canvas(S, "RGB")
    cv.img = img
    cv.draw = ImageDraw.Draw(img)
    for g, _ in D["water_poly"]:
        cv.poly(g, (70, 120, 160), (70, 120, 160))
    for g in D["water_line"]:
        cv.poly(g, (70, 120, 160))
    for t in trees[::1]:
        u, v = (t[0] + HALF) * cv.ppm, (t[1] + HALF) * cv.ppm
        cv.draw.ellipse([u - 2, v - 2, u + 2, v + 2], fill=(52, 84, 44))
    for g, _ in D["buildings"]:
        cv.poly(g, (150, 72, 58))
    for f in fields:
        c = f["geom"].exterior.coords
        cv.draw.line(cv._px(c), fill=(235, 225, 160), width=2)
    img = img.filter(__import__("PIL.ImageFilter", fromlist=["x"]).SMOOTH)
    MOD.joinpath("maps").mkdir(parents=True, exist_ok=True)
    img.save(MOD / "maps" / "overview.dds", pixel_format="DXT1")
    prev = img.resize((1024, 1024), Image.LANCZOS)
    d = ImageDraw.Draw(prev)
    for i, f in enumerate(fields, 1):
        c = f["geom"].representative_point()
        d.text(((c.x + HALF) / 4 - 5, (c.y + HALF) / 4 - 5), str(i), fill=(255, 255, 255))
    (ROOT / "docs").mkdir(exist_ok=True)
    prev.save(ROOT / "docs" / "preview.png")
    icon = img.crop((1400, 1300, 2600, 2500)).resize((512, 512), Image.LANCZOS).convert("RGBA")
    ImageDraw.Draw(icon).rectangle([0, 440, 512, 512], fill=(20, 60, 30, 220))
    ImageDraw.Draw(icon).text((20, 455), "LEDNICE", fill=(255, 255, 255, 255),
                              font=_font(44))
    icon.save(MOD / "icon_Lednice.dds", pixel_format="DXT5")
    icon.save(ROOT / "docs" / "icon.png")


def _font(size):
    from PIL import ImageFont
    for f in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",):
        if Path(f).exists():
            return ImageFont.truetype(f, size)
    return ImageFont.load_default()


def write_mod_files():
    tpl = Path(__file__).parent / "templates"
    for f in ("modDesc.xml",):
        shutil.copy(tpl / f, MOD / f)
    shutil.copy(tpl / "map.xml", MOD / "maps" / "map.xml")


def main():
    if MOD.exists():
        for sub in ("maps", "import"):
            shutil.rmtree(MOD / sub, ignore_errors=True)
    IMPORT.mkdir(parents=True, exist_ok=True)
    DATA.mkdir(parents=True, exist_ok=True)
    D = collect()
    built_up = shapely.union_all([g.buffer(4) for g, _ in D["buildings"]]
                                 + [g.buffer(ROAD_WIDTH.get(c, 3) / 2 + 1) for g, c, *_ in D["roads"]]
                                 + [g for g, _ in D["water_poly"]])
    T, base, water_levels = build_terrain(D)
    idx = build_textures(D)
    fields = build_fields(D, T, built_up)
    build_buildings(D, T)
    build_splines(D, T)
    build_water(water_levels)
    trees = build_trees(D, T, idx)
    build_overview(D, idx, fields, trees)
    write_mod_files()
    meta = {"mapSize": C.MAP_SIZE, "demSize": C.DEM_SIZE, "weightSize": C.WEIGHT_SIZE,
            "heightScale": HEIGHT_SCALE, "baseElevation_m": base,
            "center": {"lat": C.CENTER_LAT, "lon": C.CENTER_LON},
            "layers": LAYERS}
    (MOD / "maps" / "data" / "lednice_meta.json").write_text(json.dumps(meta, indent=1))
    log("hotovo")


if __name__ == "__main__":
    main()
