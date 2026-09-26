-- Author: FS25 Lednice generator
-- Name: Lednice - rozmistit stromy z trees.csv
-- Description: Naklonuje vybrane stromy (prototypy) na pozice ze souboru import/trees.csv
-- Icon:
-- Hide: no
--
-- Pouziti v Giants Editoru:
--   1. Nactete do sceny nekolik modelu stromu ze zakladni hry (napr. dub, jasan, lipa, buk)
--      a v Scenegraph je vsechny oznacte (Ctrl + klik). Budou pouzity jako vzory.
--   2. Upravte cestu CSV_PATH nize na umisteni souboru trees.csv.
--   3. Scripts -> Lednice - rozmistit stromy z trees.csv
--   Stromy se vytvori do nove skupiny "lednice_trees" (rozdelene podle typu) a posadi se na teren.

local CSV_PATH = "C:/FS25_Lednice/import/trees.csv"
local ONLY_KIND = nil -- napr. "forest", "park", "bush", "alley", "solitary"; nil = vse

local numSelected = getNumSelected()
if numSelected == 0 then
    print("Error: oznacte ve Scenegraph alespon jeden strom (prototyp).")
    return
end
local prototypes = {}
for i = 0, numSelected - 1 do
    table.insert(prototypes, getSelection(i))
end

local terrain = getChild(getRootNode(), "terrain")
local file = io.open(CSV_PATH, "r")
if file == nil then
    print("Error: nelze otevrit " .. CSV_PATH)
    return
end

local root = createTransformGroup("lednice_trees")
link(getRootNode(), root)
local groups = {}
local count = 0
local first = true
math.randomseed(25)

for line in file:lines() do
    if first then
        first = false
    else
        local x, y, z, rotY, scale, kind = line:match("([^;]+);([^;]+);([^;]+);([^;]+);([^;]+);([^;]+)")
        if x ~= nil and (ONLY_KIND == nil or kind == ONLY_KIND) then
            x, z = tonumber(x), tonumber(z)
            if groups[kind] == nil then
                groups[kind] = createTransformGroup("trees_" .. kind)
                link(root, groups[kind])
            end
            local proto = prototypes[math.random(1, #prototypes)]
            local tree = clone(proto, false, false, false)
            link(groups[kind], tree)
            local ty = tonumber(y)
            if terrain ~= nil and terrain ~= 0 then
                ty = getTerrainHeightAtWorldPos(terrain, x, 0, z)
            end
            setTranslation(tree, x, ty, z)
            setRotation(tree, 0, math.rad(tonumber(rotY)), 0)
            local s = tonumber(scale)
            setScale(tree, s, s, s)
            count = count + 1
        end
    end
end
file:close()
print(string.format("Lednice: vytvoreno %d stromu", count))
