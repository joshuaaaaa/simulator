-- Author: FS25 Lednice generator
-- Name: Lednice - posadit vybrane objekty na teren
-- Description: Nastavi vysku (Y) vsech primych potomku vybraneho uzlu podle terenu
-- Icon:
-- Hide: no
--
-- Hodi se po ruční úpravě terénu (např. pro skupinu budov nebo stromů).
-- Budovy ze souboru buildings.i3d jsou sloučené po dlaždicích a mají výšku již zapečenou,
-- tento skript je určen pro jednotlivě umístěné objekty (stromy, placeables, značky ...).

local terrain = getChild(getRootNode(), "terrain")
if terrain == nil or terrain == 0 then
    print("Error: ve scene chybi uzel 'terrain'")
    return
end
local n = 0
for s = 0, getNumSelected() - 1 do
    local parent = getSelection(s)
    for i = 0, getNumOfChildren(parent) - 1 do
        local node = getChildAt(parent, i)
        local x, _, z = getWorldTranslation(node)
        local y = getTerrainHeightAtWorldPos(terrain, x, 0, z)
        local lx, ly, lz = worldToLocal(getParent(node), x, y, z)
        setTranslation(node, lx, ly, lz)
        n = n + 1
    end
end
print(string.format("Lednice: posazeno %d objektu", n))
