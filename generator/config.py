"""Společné nastavení mapy FS25 Lednice."""
from pyproj import Transformer

# Střed mapy – obec Lednice, zámek, zámecký park s Minaretem i Janův hrad.
CENTER_LAT = 48.8040
CENTER_LON = 16.8060

# Velikost mapy v metrech (4x mapa FS25 = 4096 x 4096 m).
MAP_SIZE = 4096

# Rozlišení výsledných podkladů
DEM_SIZE = MAP_SIZE + 1          # FS25: dem.png = velikost mapy + 1 (1 m / px)
WEIGHT_SIZE = MAP_SIZE * 2       # FS25: texturové masky 0,5 m / px
INFO_SIZE = MAP_SIZE             # fieldType / farmlands 1 m / px

OVERTURE_RELEASE = "2026-09-23.1"

# UTM 33N – metrická projekce pro jižní Moravu
_to_utm = Transformer.from_crs("EPSG:4326", "EPSG:32633", always_xy=True)
_to_wgs = Transformer.from_crs("EPSG:32633", "EPSG:4326", always_xy=True)
CX, CY = _to_utm.transform(CENTER_LON, CENTER_LAT)


def lonlat_to_map(lon, lat):
    """WGS84 -> souřadnice mapy FS25 (x doprava/východ, z dolů/jih, střed = 0,0)."""
    e, n = _to_utm.transform(lon, lat)
    return e - CX, -(n - CY)


def map_to_lonlat(x, z):
    return _to_wgs.transform(x + CX, -z + CY)


def _bbox():
    h = MAP_SIZE / 2 + 100  # malá rezerva kolem okraje
    pts = [map_to_lonlat(x, z) for x in (-h, h) for z in (-h, h)]
    lons, lats = zip(*pts)
    return min(lons), min(lats), max(lons), max(lats)


BBOX_WGS84 = _bbox()
