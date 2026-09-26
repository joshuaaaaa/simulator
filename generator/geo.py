"""Načítání GeoJSON dat a převod do souřadnic mapy FS25 + rasterizace."""
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from pyproj import Transformer
from shapely.geometry import shape, box
from shapely.ops import transform

from config import CX, CY, MAP_SIZE

RAW = Path(__file__).resolve().parent.parent / "data" / "raw"
_to_utm = Transformer.from_crs("EPSG:4326", "EPSG:32633", always_xy=True)
HALF = MAP_SIZE / 2
MAP_BOX = box(-HALF, -HALF, HALF, HALF)


def _proj(lon, lat, z=None):
    e, n = _to_utm.transform(lon, lat)
    return np.asarray(e) - CX, -(np.asarray(n) - CY)


def load(name):
    """Vrátí seznam (geometrie v m souřadnicích mapy, properties), oříznuto na mapu."""
    data = json.loads((RAW / f"{name}.geojson").read_text())
    out = []
    for f in data["features"]:
        g = transform(_proj, shape(f["geometry"]))
        if not g.is_valid:
            g = g.buffer(0)
        if g.is_empty or not g.intersects(MAP_BOX):
            continue
        out.append((g, f["properties"]))
    return out


def name_of(props):
    return (props.get("names") or {}).get("primary") or ""


def iter_polys(g):
    if g.is_empty:
        return
    t = g.geom_type
    if t == "Polygon":
        yield g
    elif t in ("MultiPolygon", "GeometryCollection"):
        for p in g.geoms:
            yield from iter_polys(p)


class Canvas:
    """Rastr pokrývající celou mapu s daným rozlišením (px na metr)."""

    def __init__(self, size, mode="L", fill=0):
        self.size = size
        self.ppm = size / MAP_SIZE
        self.img = Image.new(mode, (size, size), fill)
        self.draw = ImageDraw.Draw(self.img)

    def _px(self, coords):
        return [((x + HALF) * self.ppm, (z + HALF) * self.ppm) for x, z in coords]

    def poly(self, g, value, hole_value=None):
        for p in iter_polys(g):
            ext = self._px(p.exterior.coords)
            if len(ext) >= 3:
                self.draw.polygon(ext, fill=value)
            if hole_value is not None:
                for h in p.interiors:
                    self.draw.polygon(self._px(h.coords), fill=hole_value)

    def array(self):
        return np.asarray(self.img)
