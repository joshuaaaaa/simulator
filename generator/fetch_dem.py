"""Stáhne výškopis (AWS Terrain Tiles, formát Terrarium) pro oblast mapy.

Dlaždice zoom 15 se složí do jedné mozaiky a uloží jako data/raw/dem_mosaic.npz
(výšky v metrech n. m. + georeference), aby build fungoval offline.
"""
import io
import math
import sys
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from config import BBOX_WGS84  # noqa: E402

Z = 15
URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
OUT = Path(__file__).resolve().parent.parent / "data" / "raw" / "dem_mosaic.npz"


def tile_xy(lon, lat, z):
    n = 2 ** z
    x = (lon + 180) / 360 * n
    y = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n
    return x, y


def main():
    xmin, ymin, xmax, ymax = BBOX_WGS84
    tx0, ty0 = (int(v) for v in tile_xy(xmin, ymax, Z))
    tx1, ty1 = (int(v) for v in tile_xy(xmax, ymin, Z))
    nx, ny = tx1 - tx0 + 1, ty1 - ty0 + 1
    mosaic = np.zeros((ny * 256, nx * 256), np.float32)
    for j, ty in enumerate(range(ty0, ty1 + 1)):
        for i, tx in enumerate(range(tx0, tx1 + 1)):
            with urllib.request.urlopen(URL.format(z=Z, x=tx, y=ty), timeout=60) as r:
                rgb = np.asarray(Image.open(io.BytesIO(r.read())).convert("RGB"), np.float32)
            h = rgb[..., 0] * 256 + rgb[..., 1] + rgb[..., 2] / 256 - 32768
            mosaic[j * 256:(j + 1) * 256, i * 256:(i + 1) * 256] = h
    np.savez_compressed(OUT, height=mosaic, z=Z, tx0=tx0, ty0=ty0)
    print(f"DEM: {nx}x{ny} dlaždic, výšky {mosaic.min():.1f}–{mosaic.max():.1f} m n. m.")


if __name__ == "__main__":
    main()
