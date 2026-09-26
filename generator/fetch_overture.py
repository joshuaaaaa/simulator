"""Stáhne reálná data (odvozená z OpenStreetMap) pro oblast Lednice z Overture Maps.

Overture Maps je veřejný dataset na AWS S3 (licence ODbL / CDLA), který obsahuje
budovy, silnice, využití půdy, vodní plochy atd. Výsledek se uloží jako GeoJSON
do data/raw/, aby generátor mapy fungoval i offline.
"""
import json
import sys
import time
from pathlib import Path

import pyarrow.dataset as ds
import pyarrow.fs as pfs
from shapely import wkb
from shapely.geometry import mapping

sys.path.insert(0, str(Path(__file__).parent))
from config import BBOX_WGS84, OVERTURE_RELEASE  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "data" / "raw"

LAYERS = {
    "buildings": ("buildings", "building",
                  ["id", "names", "height", "num_floors", "subtype", "class",
                   "roof_shape", "roof_height", "roof_color", "facade_color", "is_underground"]),
    "segments": ("transportation", "segment",
                 ["id", "names", "subtype", "class", "subclass", "road_surface", "road_flags", "width_rules"]),
    "land_use": ("base", "land_use", ["id", "names", "subtype", "class", "surface"]),
    "land": ("base", "land", ["id", "names", "subtype", "class", "surface"]),
    "water": ("base", "water", ["id", "names", "subtype", "class", "is_intermittent"]),
    "infrastructure": ("base", "infrastructure", ["id", "names", "subtype", "class", "surface"]),
    "places": ("places", "place", ["id", "names", "categories", "basic_category"]),
}


def to_jsonable(v):
    if isinstance(v, (list, tuple)):
        return [to_jsonable(x) for x in v]
    if isinstance(v, dict):
        return {k: to_jsonable(x) for k, x in v.items()}
    return v


def fetch(name, theme, typ, cols):
    s3 = pfs.S3FileSystem(anonymous=True, region="us-west-2")
    path = f"overturemaps-us-west-2/release/{OVERTURE_RELEASE}/theme={theme}/type={typ}"
    dset = ds.dataset(path, filesystem=s3, format="parquet")
    xmin, ymin, xmax, ymax = BBOX_WGS84
    f = lambda k: ds.field("bbox", k)  # noqa: E731
    flt = (f("xmax") >= xmin) & (f("xmin") <= xmax) & (f("ymax") >= ymin) & (f("ymin") <= ymax)
    cols = [c for c in cols if c in dset.schema.names] + ["geometry"]
    t = time.time()
    table = dset.to_table(columns=cols, filter=flt)
    feats = []
    for row in table.to_pylist():
        geom = wkb.loads(row.pop("geometry"))
        feats.append({"type": "Feature", "geometry": mapping(geom), "properties": to_jsonable(row)})
    (OUT / f"{name}.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}))
    print(f"{name}: {len(feats)} prvků ({time.time() - t:.0f} s)")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    wanted = sys.argv[1:] or list(LAYERS)
    for n in wanted:
        fetch(n, *LAYERS[n])
