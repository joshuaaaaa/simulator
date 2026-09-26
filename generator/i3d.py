"""Minimalistický zapisovač formátu GIANTS i3D (XML, verze 1.6).

Geometrie se ukládá přímo do XML (<Shapes>); Giants Editor ji při uložení
automaticky převede do binárního souboru .i3d.shapes.
"""
import unicodedata
from xml.sax.saxutils import quoteattr as _q

import numpy as np


def quoteattr(s):
    """Názvy uzlů bez diakritiky – Giants Editor s nimi nemá problém."""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return _q(s)


def _f(v):
    return f"{v:.3f}".rstrip("0").rstrip(".") if v != 0 else "0"


class Mesh:
    """Trojúhelníková síť rozdělená do podmnožin podle materiálu."""

    def __init__(self):
        self.subsets = {}  # materialId -> (verts[list], normals, tris)

    def _sub(self, mat):
        return self.subsets.setdefault(mat, ([], [], []))

    def tri(self, mat, a, b, c, want_normal=None):
        a, b, c = (np.asarray(p, float) for p in (a, b, c))
        n = np.cross(b - a, c - a)
        ln = np.linalg.norm(n)
        if ln < 1e-9:
            return
        n /= ln
        if want_normal is not None and np.dot(n, want_normal) < 0:
            b, c = c, b
            n = -n
        verts, norms, tris = self._sub(mat)
        i = len(verts)
        verts.extend([a, b, c])
        norms.extend([n, n, n])
        tris.append((i, i + 1, i + 2))

    def quad(self, mat, a, b, c, d, want_normal=None):
        self.tri(mat, a, b, c, want_normal)
        self.tri(mat, a, c, d, want_normal)

    def empty(self):
        return not any(s[2] for s in self.subsets.values())

    def to_xml(self, name, shape_id, offset):
        ox, oy, oz = offset
        mats = sorted(m for m, s in self.subsets.items() if s[2])
        verts, norms, tris, subs = [], [], [], []
        for m in mats:
            v, n, t = self.subsets[m]
            base = len(verts)
            subs.append((base, len(v), len(tris) * 3, len(t) * 3))
            verts.extend(v)
            norms.extend(n)
            tris.extend((a + base, b + base, c + base) for a, b, c in t)
        out = [f'    <IndexedTriangleSet name={quoteattr(name)} shapeId="{shape_id}">',
               f'      <Vertices count="{len(verts)}" normal="true">']
        for p, n in zip(verts, norms):
            out.append(f'        <v p="{_f(p[0] - ox)} {_f(p[1] - oy)} {_f(p[2] - oz)}" '
                       f'n="{_f(n[0])} {_f(n[1])} {_f(n[2])}"/>')
        out.append("      </Vertices>")
        out.append(f'      <Triangles count="{len(tris)}">')
        out.extend(f'        <t vi="{a} {b} {c}"/>' for a, b, c in tris)
        out.append("      </Triangles>")
        out.append(f'      <Subsets count="{len(subs)}">')
        for fv, nv, fi, ni in subs:
            out.append(f'        <Subset firstVertex="{fv}" numVertices="{nv}" firstIndex="{fi}" numIndices="{ni}"/>')
        out.append("      </Subsets>")
        out.append("    </IndexedTriangleSet>")
        return "\n".join(out), mats


class I3D:
    def __init__(self, name):
        self.name = name
        self.materials = []  # (name, rgba)
        self.shapes = []     # xml strings
        self.scene = []      # xml lines
        self._shape_id = 0
        self._node_id = 0

    def material(self, name, rgb, alpha=1.0):
        self.materials.append((name, (*rgb, alpha)))
        return len(self.materials)

    def next_shape(self):
        self._shape_id += 1
        return self._shape_id

    def next_node(self):
        self._node_id += 1
        return self._node_id

    def add_mesh(self, mesh, name, offset, indent, attrs='static="true" castsShadows="true" receiveShadows="true"'):
        sid = self.next_shape()
        xml, mats = mesh.to_xml(name, sid, offset)
        self.shapes.append(xml)
        t = " ".join(_f(v) for v in offset)
        self.scene.append(f'{indent}<Shape name={quoteattr(name)} shapeId="{sid}" nodeId="{self.next_node()}" '
                          f'translation="{t}" materialIds="{" ".join(map(str, mats))}" {attrs}/>')

    def add_spline(self, pts, name, indent):
        sid = self.next_shape()
        cvs = "\n".join(f'      <cv c="{_f(x)}, {_f(y)}, {_f(z)}"/>' for x, y, z in pts)
        self.shapes.append(f'    <NurbsCurve name={quoteattr(name)} shapeId="{sid}" degree="3" form="open">\n'
                           f'{cvs}\n    </NurbsCurve>')
        self.scene.append(f'{indent}<Shape name={quoteattr(name)} shapeId="{sid}" nodeId="{self.next_node()}"/>')

    def open_group(self, name, indent, translation=None):
        t = f' translation="{" ".join(_f(v) for v in translation)}"' if translation is not None else ""
        self.scene.append(f'{indent}<TransformGroup name={quoteattr(name)}{t} nodeId="{self.next_node()}">')

    def leaf_group(self, name, indent, translation):
        t = " ".join(_f(v) for v in translation)
        self.scene.append(f'{indent}<TransformGroup name={quoteattr(name)} translation="{t}" nodeId="{self.next_node()}"/>')

    def close_group(self, indent):
        self.scene.append(f"{indent}</TransformGroup>")

    def write(self, path):
        mats = "\n".join(
            f'    <Material name={quoteattr(n)} materialId="{i}" diffuseColor="{" ".join(_f(c) for c in rgba)}" '
            f'specularColor="0.1 1 0"/>' for i, (n, rgba) in enumerate(self.materials, 1))
        xml = f"""<?xml version="1.0" encoding="utf-8"?>
<i3D name={quoteattr(self.name)} version="1.6" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="http://i3d.giants.ch/schema/i3d-1.6.xsd">
  <Asset>
    <Export program="FS25 Lednice generator" version="1.0"/>
  </Asset>
  <Files/>
  <Materials>
{mats}
  </Materials>
  <Shapes>
{chr(10).join(self.shapes)}
  </Shapes>
  <Scene>
{chr(10).join(self.scene)}
  </Scene>
</i3D>
"""
        path.write_text(xml, encoding="utf-8")
