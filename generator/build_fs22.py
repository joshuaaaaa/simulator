"""Vytvoří verzi mapy Lednice pro Farming Simulator 22 (složka FS22_Lednice/).

Předpokládá, že už proběhl build_map.py (FS25_Lednice/). Terén, texturové masky,
pozemky, budovy, silnice, voda a stromy jsou pro obě hry stejné; liší se:
  * pole – FS22 nepoužívá polygony, ale obdélníky "fieldDimensions"
    (corner1_1 + potomci corner1_2 = šířka, corner1_3 = výška). Každé pole
    rozložíme na pruhy o šířce 5 m natočené podél delší osy pole.
  * modDesc.xml (descVersion FS22, konfigurace evropské mapy mapFR),
  * ikona 256 × 256 px.
"""
import json
import shutil
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from shapely import affinity
from shapely.geometry import LineString, Point, Polygon

sys.path.insert(0, str(Path(__file__).parent))
from build_map import height_at, log  # noqa: E402
from i3d import I3D  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "FS25_Lednice"
MOD = ROOT / "FS22_Lednice"
STRIP = 5.0          # šířka pruhu v m (přesnost okrajů pole)
MERGE_TOL = 1.0      # sousední pruhy s podobnými okraji se slučují


def terrain():
    meta = json.loads((SRC / "maps/data/lednice_meta.json").read_text())
    dem = np.asarray(Image.open(SRC / "maps/data/dem.png"), np.float32)
    return dem / 65535 * meta["heightScale"]


def field_polygons():
    """Načte polygony polí z FS25 fields.i3d (světové souřadnice x, z)."""
    import xml.etree.ElementTree as ET
    root = ET.parse(SRC / "import/fields.i3d").getroot()
    out = []
    for tg in root.iter("TransformGroup"):
        name = tg.get("name", "")
        if not (name.startswith("field") and name[5:].isdigit()):
            continue
        fx, _, fz = (float(v) for v in tg.get("translation").split())
        pts = []
        for p in tg.iter("TransformGroup"):
            if p.get("name", "").startswith("point"):
                x, _, z = (float(v) for v in p.get("translation").split())
                pts.append((fx + x, fz + z))
        out.append((int(name[5:]), Polygon(pts).buffer(0)))
    return out


def decompose(poly):
    """Rozloží polygon na obdélníky (x0, x1, y0, y1) v natočené soustavě + úhel natočení."""
    rect = poly.minimum_rotated_rectangle
    c = np.array(rect.exterior.coords[:4])
    e1, e2 = c[1] - c[0], c[2] - c[1]
    long_edge = e1 if np.linalg.norm(e1) >= np.linalg.norm(e2) else e2
    angle = float(np.degrees(np.arctan2(long_edge[1], long_edge[0])))
    origin = poly.centroid
    rp = affinity.rotate(poly, -angle, origin=origin)
    minx, miny, maxx, maxy = rp.bounds
    rects = []   # (x0, x1, y0, y1)
    open_runs = []
    y = miny
    while y < maxy - 0.5:
        y1 = min(y + STRIP, maxy)
        mid = (y + y1) / 2
        cut = LineString([(minx - 1, mid), (maxx + 1, mid)]).intersection(rp)
        segs = [cut] if cut.geom_type == "LineString" else list(getattr(cut, "geoms", []))
        spans = sorted((s.bounds[0], s.bounds[2]) for s in segs if s.geom_type == "LineString" and s.length > 1.0)
        new_runs = []
        for a, b in spans:
            run = next((r for r in open_runs if abs(r[0] - a) < MERGE_TOL and abs(r[1] - b) < MERGE_TOL), None)
            if run:
                open_runs.remove(run)
                new_runs.append((run[0], run[1], run[2], y1))
            else:
                new_runs.append((a, b, y, y1))
        rects.extend(open_runs)
        open_runs = new_runs
        y = y1
    rects.extend(open_runs)
    return rects, angle, origin


def build_fields(T):
    log("FS22: pole jako fieldDimensions")
    info = {f["id"]: f for f in json.loads((SRC / "import/fields.json").read_text(encoding="utf-8"))}
    doc = I3D("lednice_fields_fs22")
    doc.open_group("fields", "    ")
    fields_node = doc._node_id
    doc.add_user_attr(fields_node, "onCreate", "scriptCallback", "FieldUtil.onCreate")
    total_rects = 0
    for fid, poly in field_polygons():
        rects, angle, origin = decompose(poly)
        c = poly.representative_point()
        cy = float(height_at(T, c.x, c.y))
        doc.open_group(f"field{fid}", "      ", (c.x, 0, c.y))
        doc.open_group("fieldDimensions", "        ")
        for k, (x0, x1, y0, y1) in enumerate(rects, 1):
            corners = [(x0, y0), (x1, y0), (x0, y1)]
            world = [affinity.rotate(Point(p), angle, origin=origin).coords[0] for p in corners]
            ys = height_at(T, [p[0] for p in world], [p[1] for p in world])
            p1 = (world[0][0] - c.x, ys[0], world[0][1] - c.y)
            doc.open_group(f"corner{k}_1", "          ", p1)
            doc.leaf_group(f"corner{k}_2", "            ",
                           (world[1][0] - world[0][0], ys[1] - ys[0], world[1][1] - world[0][1]))
            doc.leaf_group(f"corner{k}_3", "            ",
                           (world[2][0] - world[0][0], ys[2] - ys[0], world[2][1] - world[0][1]))
            doc.close_group("          ")
        doc.close_group("        ")
        doc.leaf_group("fieldMapIndicator", "        ", (0, cy, 0))
        doc.close_group("      ")
        total_rects += len(rects)
        info.setdefault(fid, {})["obdelniku_fs22"] = len(rects)
    doc.close_group("    ")
    doc.write(MOD / "import/fields.i3d")
    (MOD / "import/fields.json").write_text(json.dumps(list(info.values()), ensure_ascii=False, indent=1),
                                           encoding="utf-8")
    log(f"FS22: {len(info)} polí, {total_rects} obdélníků fieldDimensions")


MODDESC = """<?xml version="1.0" encoding="utf-8" standalone="no"?>
<modDesc descVersion="72">
    <author>FS25 Lednice generator</author>
    <version>0.1.0.0</version>
    <title>
        <en>Lednice (CZ)</en>
        <cz>Lednice</cz>
        <de>Eisgrub / Lednice</de>
    </title>
    <description>
        <en><![CDATA[Real-world based map of the village of Lednice (South Moravia, Czech Republic) – 4x map (4096 x 4096 m). Streets, houses, fields, meadows, vineyards, the Lednice château, its gardens and the château park with the Minaret, generated from OpenStreetMap data (© OpenStreetMap contributors, ODbL) via Overture Maps.]]></en>
        <cz><![CDATA[Mapa podle skutečné obce Lednice na jižní Moravě – 4x mapa (4096 x 4096 m). Reálné ulice, domy, pole, louky, vinice, zámek Lednice, zámecká zahrada a zámecký park s Minaretem a Janovým hradem. Vygenerováno z dat OpenStreetMap (© přispěvatelé OpenStreetMap, ODbL) přes Overture Maps.]]></cz>
    </description>
    <iconFilename>icon_Lednice.dds</iconFilename>
    <multiplayer supported="true"/>

    <maps>
        <map id="MapLednice" className="Mission00" filename="$dataS/scripts/missions/mission00.lua"
             configFilename="maps/map.xml"
             defaultVehiclesXMLFilename="$data/maps/mapFR/defaultVehicles.xml"
             defaultItemsXMLFilename="$data/maps/mapFR/defaultItems.xml">
            <title>
                <en>Lednice</en>
                <cz>Lednice</cz>
            </title>
            <description>
                <en>Lednice – South Moravia, Czech Republic</en>
                <cz>Lednice – jižní Morava</cz>
            </description>
            <iconFilename>maps/overview.dds</iconFilename>
        </map>
    </maps>
</modDesc>
"""

MAPXML = """<?xml version="1.0" encoding="utf-8" standalone="no"?>
<!--
  Konfigurace mapy Lednice pro FS22. Při stavbě z šablony se použije map.xml
  šablony a install_to_template.py v něm upraví jen rozměry (viz docs/POSTUP_FS22.md).
-->
<map width="4096" height="4096" imageFilename="maps/overview.dds">
    <filename>maps/map.i3d</filename>
    <farmlands filename="maps/config/farmlands.xml"/>
</map>
"""


def main():
    if not (SRC / "maps/data/dem.png").exists():
        raise SystemExit("Nejdřív spusťte generator/build_map.py (vytvoří FS25_Lednice/).")
    if MOD.exists():
        shutil.rmtree(MOD)
    (MOD / "import").mkdir(parents=True)
    shutil.copytree(SRC / "maps", MOD / "maps")
    for f in ("buildings.i3d", "roads.i3d", "water.i3d", "trees.csv"):
        shutil.copy(SRC / "import" / f, MOD / "import" / f)
    T = terrain()
    build_fields(T)
    (MOD / "modDesc.xml").write_text(MODDESC, encoding="utf-8")
    (MOD / "maps/map.xml").write_text(MAPXML, encoding="utf-8")
    icon = Image.open(ROOT / "docs/icon.png").resize((256, 256), Image.LANCZOS)
    icon.save(MOD / "icon_Lednice.dds", pixel_format="DXT5")
    meta = json.loads((MOD / "maps/data/lednice_meta.json").read_text())
    meta["game"] = "fs22"
    (MOD / "maps/data/lednice_meta.json").write_text(json.dumps(meta, indent=1))
    log("FS22_Lednice hotovo")


if __name__ == "__main__":
    main()
