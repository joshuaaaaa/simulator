# Postup krok za krokem – mapa Lednice do FS25

Návod počítá s Windows, nainstalovaným Farming Simulatorem 25 a zhruba 5 GB volného místa.

## Část A – Příprava (jednorázově)

### Krok 1: Stáhněte soubory z GitHubu
1. Otevřete https://github.com/joshuaaaaa/simulator
2. Vlevo nahoře přepněte větev na **`claude/pensive-tesla-nl3rc3`**.
3. Klikněte na zelené tlačítko **Code → Download ZIP**.
4. ZIP rozbalte do `C:\Lednice` (bez diakritiky a mezer v cestě).
   Uvnitř musí být složky `generator`, `FS25_Lednice`, `ge_scripts` a `data`.

### Krok 2: Nainstalujte Python
1. Stáhněte Python 3.11 nebo novější z https://www.python.org/downloads/
2. Při instalaci **zaškrtněte „Add python.exe to PATH“**.
3. Otevřete příkazový řádek (Start → napište `cmd` → Enter) a zadejte:
   ```
   pip install numpy pillow
   ```

### Krok 3: Nainstalujte Giants Editor
1. Zaregistrujte se na https://gdn.giants-software.com
2. V sekci **Downloads** stáhněte **GIANTS Editor 10.x (64 bit)** pro Farming Simulator 25 a nainstalujte ho.

### Krok 4: Sežeňte prázdnou šablonu mapy FS25
Hra potřebuje soubory, které umí vytvořit jen Giants Editor (např. `.gdm`), proto se začíná ze šablony.
- **Možnost 1:** na GDN v sekci Downloads hledejte „Map Template“ nebo „Sample Mod“ pro FS25.
- **Možnost 2:** komunitní šablona FS25 z projektu *maps4fs* (GitHub `iwatkot/maps4fs`, soubor `fs25-map-template.zip` ve složce `data`).

Všimněte si, jakou má šablona velikost. Otevřete v ní soubor `maps/data/dem.png` a podívejte se na rozměr obrázku:
- **2049 × 2049** → šablona je 2x (2 km) → postupujte podle kroku 6B
- **4097 × 4097** → šablona je 4x (4 km) → přeskočte krok 6B

## Část B – Vytvoření módu

### Krok 5: Připravte složku módu
1. Otevřete `Dokumenty\My Games\FarmingSimulator2025\mods`
2. Vytvořte složku **`FS25_Lednice`**.
3. Rozbalte do ní obsah šablony, takže v ní přímo leží `modDesc.xml` a složka `maps`.
   Pozor: nesmí to vypadat jako `FS25_Lednice\nazev_sablony\modDesc.xml`.
4. Pro jistotu si celou složku zazálohujte (zkopírujte vedle sebe).

### Krok 6A: Vložte data Lednice do šablony
V příkazovém řádku zadejte (místo `JMENO` dejte své uživatelské jméno ve Windows):
```
cd C:\Lednice
python generator\install_to_template.py "C:\Users\JMENO\Documents\My Games\FarmingSimulator2025\mods\FS25_Lednice"
```
Skript vypíše, co provedl:
- nahradí výškopis (`dem.png`) a nastaví výšku terénu,
- přiřadí textury (např. `textura asphalt -> asphalt01_weight.png`),
- nahradí pozemky, mapu v PDA, ikonu a název mapy,
- zkopíruje do módu složku `lednice_import` (budovy, silnice, pole, voda, stromy, skripty).

Pokud se u některé textury objeví `!`, šablona takovou texturu nemá. Nic se neděje, jen tam bude základní tráva.

### Krok 6B (jen pro 2x šablonu): Vygenerujte menší mapu 2048 m
Připravená data jsou pro 4x mapu (4096 m). Pro 2x šablonu je nejjednodušší mapu vygenerovat znovu v menší velikosti:
1. Obnovte složku módu ze zálohy (vraťte šablonu do původního stavu).
2. Nainstalujte zbytek knihoven:
   ```
   pip install numpy scipy pillow shapely pyproj pyarrow
   ```
3. Otevřete `C:\Lednice\generator\config.py` v Poznámkovém bloku a změňte:
   ```python
   CENTER_LAT = 48.8060
   CENTER_LON = 16.8040
   MAP_SIZE = 2048
   ```
4. Spusťte generátor (trvá 1–3 minuty, data se nestahují znovu):
   ```
   cd C:\Lednice
   python generator\build_map.py
   ```
5. Pak znovu spusťte krok 6A.

Výřez 2 km obsáhne centrum obce, zámek, zámeckou zahradu a park až po Minaret. Janův hrad a část polí se do něj nevejdou.

## Část C – Giants Editor

### Krok 7: Otevřete mapu
1. Spusťte Giants Editor.
2. **File → Open** → `...\mods\FS25_Lednice\maps\map.i3d`
3. Měli byste vidět terén Lednice: rovinu s korytem Dyje a rybníky.
4. Pokud je šablona obsahovala, smažte ze scény staré objekty (budovy, stromy) ve Scenegraph (panel vlevo).

### Krok 8: Budovy
1. **File → Import** → `lednice_import\buildings.i3d`
2. Ve Scenegraph přibude skupina `lednice_buildings` s budovami rozdělenými do dlaždic 512 × 512 m.
   Budovy už jsou ve správné výšce a mají kolize.
3. Pro kontrolu najděte zámek (střed mapy mírně vlevo nahoře od náměstí) a Minaret (62 m vysoká věž v parku).

### Krok 9: Voda
1. **File → Import** → `lednice_import\water.i3d`
2. Hladiny dostanou dočasný modrý materiál. Aby vypadaly jako voda:
   - najděte ve šabloně existující vodní plochu (typicky ve skupině `water`),
   - otevřete **Window → Material Editor**, vyberte její materiál a přiřaďte ho hladinám ze skupiny `waterPlanes`.
3. Pokud šablona vodní plochu nemá, zkopírujte si ji z ukázkové mapy GIANTS.

### Krok 10: Pole
1. **File → Import** → `lednice_import\fields.i3d`
2. Ve Scenegraph najděte v šabloně skupinu **`fields`** (bývá v `gameplay` nebo přímo v kořeni).
3. Otevřete jedno původní pole šablony (např. `field1`) a podívejte se, co obsahuje: podskupiny a atributy v **Attributes** / **User Attributes**.
4. Smažte původní pole šablony a přetáhněte do skupiny `fields` všechna pole `field01`–`fieldNN` z importu.
5. Pokud měla původní pole ještě další podřízené uzly nebo uživatelské atributy, doplňte je stejně i našim polím.
6. Seznam polí s výměrou a typem (orná, louka, vinice, sad) je v `lednice_import\fields.json`.

### Krok 11: Silnice (volitelné)
Silnice jsou už namalované texturou v terénu, takže tenhle krok není nutný.
- **File → Import** → `lednice_import\roads.i3d`
- Spline křivky se hodí pro AI dopravu nebo jako vodítko pro umisťování obrubníků, značek a lamp.

### Krok 12: Stromy
1. Zkopírujte `lednice_import\ge_scripts\lednicePlaceTrees.lua` do složky skriptů Giants Editoru (v editoru ji najdete přes menu **Scripts**, případně `C:\Program Files\GIANTS Software\GIANTS_Editor_10...\scripts`) a editor restartujte.
2. Soubor otevřete v Poznámkovém bloku a upravte cestu na řádku `CSV_PATH`, např.:
   ```lua
   local CSV_PATH = "C:/Users/JMENO/Documents/My Games/FarmingSimulator2025/mods/FS25_Lednice/lednice_import/trees.csv"
   ```
   Používejte lomítka `/`.
3. Doporučení: nastavte nejdřív `local ONLY_KIND = "park"`. Celkem je v CSV asi 58 000 stromů, začněte zámeckým parkem.
4. Do scény naimportujte 3–5 stromů ze hry (listnaté: dub, jasan, lípa, topol – odpovídá lužnímu lesu). Najdete je ve složce hry `data\maps\trees`.
5. Ve Scenegraph je všechny označte (Ctrl + klik).
6. Spusťte **Scripts → Lednice - rozmistit stromy z trees.csv**.
7. Potom zopakujte pro `"forest"`, `"alley"`, `"solitary"` a `"bush"` (pro keře použijte modely keřů).
8. Původní vzorové stromy nakonec smažte.

### Krok 13: Dolaďte vzhled
- **Terrain Editing → Paint:** doladit textury, například okolí budov.
- **Foliage Paint:** namalovat trávu na louky, do parku a na zahrady (na pole ne, ta hra vytvoří sama).
- **Vinice:** u polí typu *vinice* (viz `fields.json`) umístěte ve hře vinné keře (placeable Grapes).
- **Ctrl + S** průběžně ukládat.

## Část D – Test ve hře

### Krok 14: Spusťte hru
1. Spusťte FS25 → **Kariéra → Nová hra**.
2. Mezi mapami vyberte **Lednice**.
3. Zkontrolujte, že sedí terén, budovy, pole i koupě pozemků (v menu Mapa → Pozemky).

### Krok 15: Když něco nefunguje
Po každém spuštění hry se podívejte do souboru `Dokumenty\My Games\FarmingSimulator2025\log.txt` a hledejte řádky `Error` nebo `Warning`.

| Problém | Řešení |
|---|---|
| Mapa není v seznamu | `modDesc.xml` musí ležet přímo ve `mods\FS25_Lednice\`, ne o složku hlouběji |
| Terén je placatý nebo obrovský | V `map.i3d` u `TerrainTransformGroup` musí být `heightScale="255"` (skript to nastavuje) |
| Chyba o velikosti density map | Šablona je 2x, ale data 4x → udělejte krok 6B |
| Budovy levitují nebo jsou zapadlé | Terén byl upraven po importu → přegenerujte nebo posuňte skupinu |
| Pole nejdou obdělávat | Pole nejsou ve správné skupině `fields` nebo jim chybí atributy ze šablony (krok 10) |
| Hra je pomalá | Příliš mnoho stromů → v kroku 12 vložte jen část (např. jen `park` a `alley`) |

Pokud se v logu objeví chyba, pošlete mi ji a opravím generátor.
