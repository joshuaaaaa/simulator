# Postup krok za krokem – mapa Lednice do Farming Simulatoru 22

Verze pro FS22 je ve složce **`FS22_Lednice/`**. Terén, textury, budovy, silnice, voda,
stromy a pozemky jsou stejné jako u FS25. Rozdíl je hlavně v polích: FS22 je neumí zadat
jako mnohoúhelník, proto je každé pole složené z obdélníků („fieldDimensions“, pruhy široké 5 m).

K vytvoření i hraní mapy potřebujete **nainstalovaný Farming Simulator 22**. Bez hry mapu
v Giants Editoru neotevřete a ve hře nespustíte.

## Část A – Příprava

### Krok 1: Stáhněte soubory
1. Otevřete https://github.com/joshuaaaaa/simulator a přepněte větev na **`claude/pensive-tesla-nl3rc3`**.
2. Klikněte na **Code → Download ZIP** a rozbalte ho do `C:\Lednice`.

### Krok 2: Python
1. Nainstalujte Python 3.11+ z https://www.python.org (zaškrtněte **„Add python.exe to PATH“**).
2. V příkazovém řádku zadejte `pip install numpy pillow`.

### Krok 3: Giants Editor 9 (pro FS22)
1. Na https://gdn.giants-software.com v sekci Downloads stáhněte **GIANTS Editor 9.0.x** – verzi pro FS22, ne 10.x pro FS25.
2. Po instalaci otevřete **File → Preferences** a do **Game installation path** zadejte složku s FS22, například:
   - Steam: `C:\Program Files (x86)\Steam\steamapps\common\Farming Simulator 22`
   - Epic: `C:\Program Files\Epic Games\FarmingSimulator22`
3. Editor restartujte.

### Krok 4: Prázdná šablona mapy FS22
Sežeňte prázdnou šablonu mapy pro FS22 (na GDN nebo v komunitě se hledá jako „FS22 map template“),
ideálně **4x (4 km)**. Velikost ověříte podle výškopisu `dem.png` nebo `map_dem.png`:
- **4097 × 4097 px**: 4x šablona, sedí přesně na Lednici,
- **2049 × 2049 px**: 2x šablona, postupujte jako v kroku 6B návodu pro FS25 ([POSTUP.md](POSTUP.md)) a potom spusťte i `python generator\build_fs22.py`.

## Část B – Vytvoření módu

### Krok 5: Složka módu
1. Otevřete `Dokumenty\My Games\FarmingSimulator2022\mods`.
2. Vytvořte složku **`FS22_Lednice`** a rozbalte do ní šablonu tak, aby v ní přímo ležel `modDesc.xml`.
3. Celou složku si zazálohujte.

### Krok 6: Vložte data Lednice
V příkazovém řádku zadejte (místo `JMENO` dejte své uživatelské jméno ve Windows):
```
cd C:\Lednice
python generator\install_to_template.py "C:\Users\JMENO\Documents\My Games\FarmingSimulator2022\mods\FS22_Lednice" --hra fs22
```
Nezapomeňte na **`--hra fs22`** na konci. Skript nahradí výškopis, textury (umí i názvy s předponou
`map_`, např. `map_asphalt01_weight.png`), pozemky, přehledku, ikonu a název a zkopíruje
do módu složku `lednice_import`.

## Část C – Giants Editor 9

### Krok 7: Otevřete mapu
**File → Open** → `...\mods\FS22_Lednice\maps\map.i3d`. Staré objekty šablony smažte.

### Krok 8: Budovy, voda, silnice
- **File → Import** → `lednice_import\buildings.i3d` (budovy jsou ve správné výšce a mají kolize).
- **File → Import** → `lednice_import\water.i3d`. Hladinám přiřaďte materiál vody ze šablony.
- **File → Import** → `lednice_import\roads.i3d` (volitelné, spline křivky pro AI dopravu).

### Krok 9: Pole
1. **File → Import** → `lednice_import\fields.i3d`.
2. Každé pole `field1`–`field157` obsahuje:
   - `fieldDimensions` s obdélníky `cornerN_1` (roh), `cornerN_2` (šířka) a `cornerN_3` (výška),
   - `fieldMapIndicator` (místo pro číslo pole na mapě).
3. Ve Scenegraph najděte skupinu **`fields`** šablony a podívejte se, jak je postavené její původní pole.
   Pokud má další uzly nebo atributy (Attributes / User Attributes), doplňte je i našim polím.
4. Původní pole šablony smažte a naše pole přetáhněte do skupiny `fields` šablony.
5. Pole potom v editoru „zasejte“: v FS22 se orná půda na polích maluje
   (**Terrain → Foliage / Field ground**, typ „cultivated“ nebo „ploughed“) v obrysu polí.
   Hranice ukazují zelené obdélníky `fieldDimensions`.

### Krok 10: Stromy
Stejně jako u FS25 (krok 12 v [POSTUP.md](POSTUP.md)): skript `lednice_import\ge_scripts\lednicePlaceTrees.lua`,
upravit v něm cestu `CSV_PATH`, označit vzorové stromy ze hry (`data\maps\trees`) a spustit
**Scripts → Lednice - rozmistit stromy z trees.csv**. Začněte s `ONLY_KIND = "park"`.

### Krok 11: Uložit a hrát
1. Uložte mapu (**Ctrl + S**).
2. Spusťte FS22 → **Kariéra → Nová hra → Lednice**.
3. Chyby hledejte v `Dokumenty\My Games\FarmingSimulator2022\log.txt` (řádky `Error`).

## Časté problémy

| Problém | Řešení |
|---|---|
| Editor hlásí „game installation path is not set“ | Krok 3.2 – nastavit cestu k FS22 a restartovat editor |
| Editor zamrzne a spadne | Šablona má jinou velikost než data (2x vs 4x), viz krok 4 |
| Mapa není ve hře | `modDesc.xml` musí ležet přímo ve `mods\FS22_Lednice\` |
| Pole nejdou koupit ani obdělávat | Pole nejsou ve skupině `fields` šablony nebo jim chybí atributy (krok 9) |

Chybu z logu mi pošlete a opravím generátor.
