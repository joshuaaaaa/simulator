"""Vloží vygenerovaná data Lednice do rozbalené šablony mapy FS25.

Použití:
    python generator/install_to_template.py <složka_šablony>

<složka_šablony> je rozbalená mapa FS25 (např. oficiální "Map Template" od GIANTS
z GDN, nebo kopie jiné prázdné mapy). Skript:
  * najde dem.png a map .i3d s terénem a nahradí výškopis (a nastaví heightScale),
  * přiřadí naše texturové masky k vrstvám šablony podle názvu (asphalt01, grass01, ...),
    ostatní vrstvy šablony vynuluje,
  * nahradí infoLayer_farmlands.png a farmlands.xml,
  * zkopíruje overview.dds, ikonu, upraví modDesc.xml a map.xml (název, rozměr 4096),
  * zkopíruje import/*.i3d (budovy, silnice, pole, voda) a trees.csv do šablony.
Nic nemaže mimo šablonu. Doporučujeme pracovat na kopii šablony.
"""
import argparse
import json
import re
import shutil
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
MOD = ROOT / "FS25_Lednice"
DATA = MOD / "maps" / "data"

# náš název vrstvy -> kandidáti v šabloně (první nalezený vyhrává)
CANDIDATES = {
    "grass": ["grass01", "grassFreshMiddle01", "grassFreshShort01", "grass"],
    "grassMeadow": ["grassClovers01", "grassFreshMiddle01", "grass02", "grass01", "grass"],
    "field": ["mudDark01", "mudLight01", "mud01", "grassDirtPatchy01", "grass01"],
    "fieldLight": ["mudLight01", "mudDark01", "grass01"],
    "forest": ["forestGrass01", "forestGround01", "forestLeaves01", "grass01"],
    "scrub": ["grassDirtPatchy01", "forestGrass01", "grass01"],
    "wetland": ["mudDarkGrassPatchy01", "grassMoss01", "riverMud01", "grass01"],
    "garden": ["grassCut01", "grassFreshShort01", "grass01"],
    "concrete": ["concrete01", "concretePebbles01", "asphalt01"],
    "mudTracks": ["mudTracks01", "gravelDirtMoss01", "gravel01"],
    "gravel": ["gravel01", "gravelSmall01", "gravelPebblesMoss01", "sand01"],
    "riverMud": ["riverMud01", "mudDark01", "sand01"],
    "asphalt": ["asphalt01", "asphaltDusty01", "asphalt"],
}


def find_one(root, pattern, predicate=None):
    for p in sorted(root.rglob(pattern)):
        if predicate is None or predicate(p):
            return p
    return None


def diagnose(tpl):
    """Srozumitelné chyby pro nejčastější problémy se složkou šablony."""
    if not tpl.exists():
        raise SystemExit(
            f"Složka neexistuje: {tpl}\n"
            "Zkontrolujte cestu – musí být v uvozovkách a za uvozovkami už nic nesmí být.\n"
            'Příklad: python generator/install_to_template.py "C:/Users/JMENO/Documents/My Games/'
            'FarmingSimulator2025/mods/FS25_Lednice"')
    if not tpl.is_dir():
        raise SystemExit(f"Cesta vede na soubor, ne na složku: {tpl}\nPokud je to .zip, nejdřív ho rozbalte.")
    items = sorted(tpl.iterdir())
    if not items:
        raise SystemExit(f"Složka {tpl} je prázdná – rozbalte do ní šablonu mapy (krok 5 v docs/POSTUP.md).")
    zips = [p.name for p in items if p.suffix.lower() == ".zip"]
    if zips and not any(tpl.rglob("*.i3d")):
        raise SystemExit(f"Ve složce je jen archiv {', '.join(zips)} – rozbalte ho přímo do {tpl}.")
    if not any(tpl.rglob("*.i3d")):
        listing = ", ".join(p.name for p in items[:20])
        raise SystemExit(f"Ve složce {tpl} není žádný .i3d soubor, takže to není mapa FS25.\n"
                         f"Obsah složky: {listing}")


def set_attr(text, tag, attr, value):
    """Nastaví atribut u prvního výskytu tagu (zachová zbytek XML beze změny)."""
    m = re.search(rf"<{tag}\b[^>]*>", text)
    if not m:
        return text, False
    el = m.group(0)
    if re.search(rf'\b{attr}="[^"]*"', el):
        new = re.sub(rf'\b{attr}="[^"]*"', f'{attr}="{value}"', el, count=1)
    else:
        new = el.replace(f"<{tag}", f'<{tag} {attr}="{value}"', 1)
    return text[:m.start()] + new + text[m.end():], True


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("template", type=Path)
    a = ap.parse_args()
    tpl = a.template.resolve()
    meta = json.loads((DATA / "lednice_meta.json").read_text())
    report = []

    # --- výškopis ---
    diagnose(tpl)
    dem_t = find_one(tpl, "dem.png")
    if dem_t is None:
        alt = sorted(p for p in tpl.rglob("*.png") if "dem" in p.name.lower())
        if len(alt) == 1:
            dem_t = alt[0]
            print(f"Používám výškopis {dem_t.relative_to(tpl)}")
        else:
            others = [str(p.relative_to(tpl)) for p in alt] or ["žádný"]
            raise SystemExit("V šabloně jsem nenašel dem.png. Soubory s 'dem' v názvu: " + ", ".join(others))
    data_dir = dem_t.parent
    old = Image.open(dem_t).size
    shutil.copy(DATA / "dem.png", dem_t)
    report.append(f"dem.png: {old[0]} px -> {meta['demSize']} px ({dem_t.relative_to(tpl)})")
    if old[0] != meta["demSize"]:
        report.append("  ! Šablona má jinou velikost terénu. Density mapy (densityMap_*.gdm) je nutné "
                      "zvětšit na 2x šablonu – viz README, sekce 'Velikost mapy'.")

    map_i3d = find_one(tpl, "*.i3d", lambda p: "<TerrainTransformGroup" in p.read_text(errors="ignore"))
    if map_i3d:
        t = map_i3d.read_text(errors="ignore")
        t, _ = set_attr(t, "TerrainTransformGroup", "heightScale", f"{meta['heightScale']:g}")
        t, _ = set_attr(t, "TerrainTransformGroup", "unitsPerPixel", "1")
        map_i3d.write_text(t)
        report.append(f"{map_i3d.relative_to(tpl)}: heightScale={meta['heightScale']:g}, unitsPerPixel=1")
    else:
        report.append("! Nenalezen .i3d s TerrainTransformGroup – heightScale nastavte ručně na 255.")

    # --- texturové masky ---
    tpl_weights = {p.name[:-len("_weight.png")].lower(): p for p in data_dir.glob("*_weight.png")}
    assigned = {}
    for layer in meta["layers"]:
        target = next((c for c in CANDIDATES[layer] if c.lower() in tpl_weights), None)
        if target is None:
            report.append(f"! vrstva '{layer}' nemá v šabloně odpovídající texturu – vynechána")
            continue
        m = np.asarray(Image.open(DATA / f"lednice_{layer}_weight.png"))
        key = target.lower()
        assigned[key] = np.maximum(assigned[key], m) if key in assigned else m
        report.append(f"textura {layer:12s} -> {tpl_weights[key].name}")
    size = meta["weightSize"]
    for key, path in tpl_weights.items():
        arr = assigned.get(key, np.zeros((size, size), np.uint8))
        Image.fromarray(arr).save(path)
    report.append(f"vynulováno dalších vrstev šablony: {len(set(tpl_weights) - set(assigned))}")

    # --- pozemky ---
    fl_t = find_one(tpl, "infoLayer_farmlands.png")
    if fl_t:
        sz = Image.open(fl_t).size
        img = Image.open(DATA / "infoLayer_farmlands.png")
        if sz[0] != img.size[0]:
            img = img.resize(sz, Image.NEAREST)
        img.save(fl_t)
        report.append(f"{fl_t.relative_to(tpl)} ({sz[0]} px)")
    fx_t = find_one(tpl, "farmlands.xml")
    if fx_t:
        ours = (MOD / "maps" / "config" / "farmlands.xml").read_text(encoding="utf-8")
        body = re.search(r"<farmlands\b.*?</farmlands>", ours, re.S).group(0)
        t = fx_t.read_text(encoding="utf-8", errors="ignore")
        t = re.sub(r"<farmlands\b.*?</farmlands>", lambda _: body, t, count=1, flags=re.S)
        fx_t.write_text(t, encoding="utf-8")
        report.append(f"{fx_t.relative_to(tpl)}: {body.count('<farmland ')} pozemků")

    # --- přehledka, ikona, modDesc, map.xml ---
    ov_t = find_one(tpl, "overview.dds")
    shutil.copy(MOD / "maps" / "overview.dds", ov_t or (tpl / "maps" / "overview.dds"))
    shutil.copy(MOD / "icon_Lednice.dds", tpl / "icon_Lednice.dds")
    md = tpl / "modDesc.xml"
    if md.exists():
        t = md.read_text(encoding="utf-8", errors="ignore")
        ours = (MOD / "modDesc.xml").read_text(encoding="utf-8")
        for tag in ("title", "description"):
            t = re.sub(rf"<{tag}>.*?</{tag}>", re.search(rf"<{tag}>.*?</{tag}>", ours, re.S).group(0), t,
                       count=1, flags=re.S)
        t = re.sub(r"<iconFilename>[^<]*</iconFilename>", "<iconFilename>icon_Lednice.dds</iconFilename>", t, count=1)
        t, _ = set_attr(t, "map", "size", str(meta["mapSize"]))
        md.write_text(t, encoding="utf-8")
        report.append("modDesc.xml: název, popis, ikona, size")
    mx = find_one(tpl, "map.xml", lambda p: "<map" in p.read_text(errors="ignore"))
    if mx:
        t = mx.read_text(encoding="utf-8", errors="ignore")
        t, _ = set_attr(t, "map", "width", str(meta["mapSize"]))
        t, _ = set_attr(t, "map", "height", str(meta["mapSize"]))
        mx.write_text(t, encoding="utf-8")
        report.append(f"{mx.relative_to(tpl)}: width/height = {meta['mapSize']}")

    dst = tpl / "lednice_import"
    shutil.copytree(MOD / "import", dst, dirs_exist_ok=True)
    shutil.copytree(ROOT / "ge_scripts", dst / "ge_scripts", dirs_exist_ok=True)
    report.append(f"import soubory -> {dst.relative_to(tpl)}/ (buildings.i3d, roads.i3d, fields.i3d, water.i3d, trees.csv)")
    print("\n".join(report))
    print("\nHotovo. Pokračujte v Giants Editoru podle README (kroky 4–8).")


if __name__ == "__main__":
    main()
