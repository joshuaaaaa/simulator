"""Export vygenerované mapy Lednice do kompaktních binárních souborů pro 3D prohlížečku (web3d/).

Vstupem jsou výstupy build_map.py (FS25_Lednice/), výstupem web3d/data/*.
"""
import base64
import json
import struct
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, str(Path(__file__).parent))
import config as C  # noqa: E402
from build_map import COLORS, LAYERS  # noqa: E402
from geo import Canvas, HALF, load  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MOD = ROOT / "FS25_Lednice"
OUT = ROOT / "web3d" / "data"
TERRAIN_STEP = 8          # 1 vzorek na 8 m -> 513 x 513
TEX_SIZE = 4096           # textura terénu 1 m/px


def terrain():
    meta = json.loads((MOD / "maps/data/lednice_meta.json").read_text())
    dem = np.asarray(Image.open(MOD / "maps/data/dem.png"), np.float32) / 65535 * meta["heightScale"]
    h = dem[::TERRAIN_STEP, ::TERRAIN_STEP]
    cm = np.round(h * 100).astype("<u2")
    (OUT / "terrain.bin").write_bytes(cm.tobytes())
    return dem, meta, h.shape[0]


def ground_texture():
    step = C.WEIGHT_SIZE // TEX_SIZE
    idx = np.zeros((TEX_SIZE, TEX_SIZE), np.uint8)
    for k, name in enumerate(LAYERS):
        m = np.asarray(Image.open(MOD / f"maps/data/lednice_{name}_weight.png"))[::step, ::step]
        idx[m > 0] = k
    pal = np.array([COLORS[k] for k in LAYERS], np.uint8)
    rgb = pal[idx].astype(np.int16)
    # jemný šum, aby plochy nepůsobily jako výplň z Malování
    rng = np.random.default_rng(1)
    rgb += rng.integers(-7, 8, (TEX_SIZE, TEX_SIZE, 1), dtype=np.int16)
    img = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8))
    cv = Canvas(TEX_SIZE, "RGB")
    cv.img, cv.draw = img, ImageDraw.Draw(img)
    for g, p in load("water"):
        if g.geom_type in ("Polygon", "MultiPolygon") and p.get("subtype") != "human_made":
            cv.poly(g, (64, 104, 118), (148, 176, 96))
    img = img.filter(ImageFilter.GaussianBlur(0.6))
    img.save(OUT / "ground.jpg", quality=84, optimize=True)


def parse_meshes(path):
    """Vrátí seznam (pozice Nx3 světové, id materiálu na vrchol) z i3d s IndexedTriangleSet."""
    root = ET.parse(path).getroot()
    mats = {m.get("materialId"): [float(x) for x in m.get("diffuseColor").split()[:3]]
            for m in root.iter("Material")}
    nodes = {s.get("shapeId"): s for s in root.iter("Shape")}
    out = []
    for its in root.iter("IndexedTriangleSet"):
        node = nodes[its.get("shapeId")]
        off = np.array([float(x) for x in node.get("translation", "0 0 0").split()])
        mids = node.get("materialIds").split()
        V = np.array([[float(x) for x in v.get("p").split()] for v in its.iter("v")]) + off
        T = np.array([[int(x) for x in t.get("vi").split()] for t in its.iter("t")])
        for sub, mid in zip(its.iter("Subset"), mids):
            fi, ni = int(sub.get("firstIndex")) // 3, int(sub.get("numIndices")) // 3
            tri = T[fi:fi + ni].ravel()
            out.append((V[tri], mats[mid]))
    return out


def write_mesh(parts, name):
    pos = np.concatenate([p for p, _ in parts])
    col = np.concatenate([np.tile(np.round(np.array(c) * 255), (len(p), 1)) for p, c in parts])
    q = np.round(pos * 10).astype("<i2")          # 0,1 m přesnost, rozsah ±3276 m
    (OUT / f"{name}.bin").write_bytes(struct.pack("<I", len(q)) + q.tobytes() + col.astype(np.uint8).tobytes())
    return len(q)


def trees(dem):
    rows = []
    kinds = {"forest": 0, "park": 1, "alley": 2, "solitary": 2, "bush": 3}
    for ln in (MOD / "import/trees.csv").read_text(encoding="utf-8").splitlines()[1:]:
        x, y, z, rot, sc, kind = ln.split(";")
        rows.append((float(x), float(y), float(z), float(sc), kinds.get(kind, 0)))
    a = np.array(rows)
    xz = np.round(a[:, [0, 2]] * 10).astype("<i2")
    y = np.round(a[:, 1] * 100).astype("<u2")
    extra = np.stack([np.round(a[:, 3] * 100), a[:, 4]], 1).astype(np.uint8)
    buf = struct.pack("<I", len(a)) + xz.tobytes() + y.tobytes() + extra.tobytes()
    (OUT / "trees.bin").write_bytes(buf)
    return len(a)


def fields():
    root = ET.parse(MOD / "import/fields.i3d").getroot()
    info = {f["id"]: f for f in json.loads((MOD / "import/fields.json").read_text(encoding="utf-8"))}
    out = []
    for tg in root.iter("TransformGroup"):
        name = tg.get("name", "")
        if not (name.startswith("field") and name[5:].isdigit()):
            continue
        fx, _, fz = (float(v) for v in tg.get("translation").split())
        pts = []
        for p in tg.iter("TransformGroup"):
            if p.get("name", "").startswith("point"):
                x, y, z = (float(v) for v in p.get("translation").split())
                pts.append([round(fx + x, 1), round(y, 2), round(fz + z, 1)])
        fid = int(name[5:])
        f = info.get(fid, {})
        out.append({"id": fid, "typ": f.get("typ"), "ha": f.get("vymera_ha"), "p": pts})
    return out


LANDMARKS = [
    ("Zámek Lednice", 16.8055, 48.8016),
    ("Zámecký skleník", 16.8070, 48.8015),
    ("Minaret", 16.8127, 48.8142),
    ("Janův hrad", 16.8323, 48.8046),
    ("Kostel sv. Jakuba", 16.8054, 48.8014),
    ("Zámecký rybník", 16.8091, 48.8095),
    ("Čínský pavilon", 16.8097, 48.8016),
    ("Maurská vodárna", 16.8079, 48.8031),
    ("Lázně Lednice", 16.8116, 48.7956),
    ("Zámecká zahrada", 16.8066, 48.8001),
]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    dem, meta, n = terrain()
    ground_texture()
    nb = write_mesh(parse_meshes(MOD / "import/buildings.i3d"), "buildings")
    nw = write_mesh(parse_meshes(MOD / "import/water.i3d"), "water")
    nt = trees(dem)
    fl = fields()
    lm = []
    for name, lon, lat in LANDMARKS:
        x, z = C.lonlat_to_map(lon, lat)
        y = float(dem[int(np.clip(z + HALF, 0, C.MAP_SIZE)), int(np.clip(x + HALF, 0, C.MAP_SIZE))])
        lm.append({"name": name, "x": round(x, 1), "y": round(y, 1), "z": round(z, 1)})
    scene = {"mapSize": C.MAP_SIZE, "terrainN": n, "terrainStep": TERRAIN_STEP,
             "baseElevation": meta["baseElevation_m"], "landmarks": lm, "fields": fl,
             "counts": {"buildingVerts": nb, "waterVerts": nw, "trees": nt}}
    (OUT / "scene.json").write_text(json.dumps(scene, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    # hosting artefaktů neservíruje binární soubory -> base64 v .txt
    for b in sorted(OUT.glob("*.bin")):
        b.with_suffix(".b64.txt").write_text(base64.b64encode(b.read_bytes()).decode())
        b.unlink()
    for f in sorted(OUT.iterdir()):
        print(f"{f.name:16s} {f.stat().st_size / 1e6:6.2f} MB")
    print(scene["counts"], "polí:", len(fl))


if __name__ == "__main__":
    main()
