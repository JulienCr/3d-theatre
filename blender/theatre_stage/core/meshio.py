"""Pure-Python readers for the mesh files a fixture sheet cites (`.obj`, `.glb`).

They return `core.meshes.Mesh` (vertices, faces) in metres, ready for
`Mesh.from_pydata`. No materials, normals, UVs or animation are read.
"""

from __future__ import annotations

import json
import math
import struct
from pathlib import Path

from .meshes import Mesh

_GLB_MAGIC = 0x46546C67
_CHUNK_JSON = 0x4E4F534A
_CHUNK_BIN = 0x004E4942
_TRIANGLES = 4
_COMPONENT = {5120: ("b", 1), 5121: ("B", 1), 5122: ("h", 2), 5123: ("H", 2), 5125: ("I", 4),
              5126: ("f", 4)}
_COMPONENTS = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def read_mesh(path) -> Mesh:
    """Read a `.obj` or `.glb` file chosen by its extension."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".obj":
        return read_obj(path)
    if suffix == ".glb":
        return read_glb(path)
    raise ValueError(f"Format de maillage non pris en charge : {path.name}")


def bounds(mesh: Mesh) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """(min corner, max corner) of a mesh."""
    xs, ys, zs = zip(*mesh.vertices)
    return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))


# --------------------------------------------------------------------- OBJ

def read_obj(path) -> Mesh:
    """Vertices (`v`) and faces (`f`, 1-based or negative indices) of every object, merged."""
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, ...]] = []
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "v" and len(parts) >= 4:
            vertices.append((float(parts[1]), float(parts[2]), float(parts[3])))
        elif parts[0] == "f" and len(parts) >= 4:
            indices = []
            for token in parts[1:]:
                raw = int(token.split("/")[0])
                indices.append(raw - 1 if raw > 0 else len(vertices) + raw)
            faces.append(tuple(indices))
    return Mesh(tuple(vertices), tuple(faces))


def write_obj(path, mesh: Mesh, name: str = "mesh") -> None:
    """Write `mesh` as Wavefront OBJ with LF newlines."""
    lines = [f"o {name}"]
    lines += [f"v {x:.6f} {y:.6f} {z:.6f}" for x, y, z in mesh.vertices]
    lines += ["f " + " ".join(str(i + 1) for i in face) for face in mesh.faces]
    Path(path).write_bytes(("\n".join(lines) + "\n").encode("utf-8"))


# --------------------------------------------------------------------- GLB

def read_glb(path, z_up: bool = True) -> Mesh:
    """Triangle meshes of the default scene (or all root nodes), node transforms applied.

    glTF is Y-up; with `z_up` (default) points become Blender-style Z-up, (x, y, z) -> (x, -z, y).
    """
    data = Path(path).read_bytes()
    if len(data) < 20 or struct.unpack_from("<I", data, 0)[0] != _GLB_MAGIC:
        raise ValueError(f"Fichier GLB invalide : {Path(path).name}")
    document, binary = _glb_chunks(data)
    reader = _GltfReader(document, binary, z_up)
    scene_index = document.get("scene", 0)
    scenes = document.get("scenes") or []
    if scenes:
        roots = scenes[scene_index].get("nodes", [])
    else:
        children = {c for n in document.get("nodes", []) for c in n.get("children", [])}
        roots = [i for i in range(len(document.get("nodes", []))) if i not in children]
    identity = _identity()
    for root in roots:
        reader.visit(root, identity)
    return Mesh(tuple(reader.vertices), tuple(reader.faces))


def _glb_chunks(data: bytes) -> tuple[dict, bytes]:
    total = struct.unpack_from("<I", data, 8)[0]
    pos, document, binary = 12, None, b""
    while pos + 8 <= min(total, len(data)):
        length, kind = struct.unpack_from("<II", data, pos)
        body = data[pos + 8:pos + 8 + length]
        if kind == _CHUNK_JSON:
            document = json.loads(body.decode("utf-8"))
        elif kind == _CHUNK_BIN and not binary:
            binary = body
        pos += 8 + length + (-length % 4)
    if document is None:
        raise ValueError("Fichier GLB sans bloc JSON.")
    return document, binary


def _identity() -> list[float]:
    return [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]


def _multiply(a, b):
    """Column-major 4x4 product `a @ b`."""
    return [sum(a[k * 4 + r] * b[c * 4 + k] for k in range(4)) for c in range(4) for r in range(4)]


def _node_matrix(node: dict) -> list[float]:
    if "matrix" in node:
        return [float(v) for v in node["matrix"]]
    x, y, z, w = node.get("rotation", (0.0, 0.0, 0.0, 1.0))
    n = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
    x, y, z, w = x / n, y / n, z / n, w / n
    sx, sy, sz = node.get("scale", (1.0, 1.0, 1.0))
    tx, ty, tz = node.get("translation", (0.0, 0.0, 0.0))
    return [
        (1 - 2 * (y * y + z * z)) * sx, (2 * (x * y + z * w)) * sx, (2 * (x * z - y * w)) * sx, 0.0,
        (2 * (x * y - z * w)) * sy, (1 - 2 * (x * x + z * z)) * sy, (2 * (y * z + x * w)) * sy, 0.0,
        (2 * (x * z + y * w)) * sz, (2 * (y * z - x * w)) * sz, (1 - 2 * (x * x + y * y)) * sz, 0.0,
        tx, ty, tz, 1.0,
    ]


class _GltfReader:
    def __init__(self, document: dict, binary: bytes, z_up: bool):
        self.doc = document
        self.binary = binary
        self.z_up = z_up
        self.vertices: list[tuple[float, float, float]] = []
        self.faces: list[tuple[int, ...]] = []

    def visit(self, index: int, parent) -> None:
        node = self.doc["nodes"][index]
        matrix = _multiply(parent, _node_matrix(node))
        if "mesh" in node:
            for primitive in self.doc["meshes"][node["mesh"]].get("primitives", []):
                self._primitive(primitive, matrix)
        for child in node.get("children", []):
            self.visit(child, matrix)

    def _accessor(self, index: int) -> list[tuple]:
        accessor = self.doc["accessors"][index]
        view = self.doc["bufferViews"][accessor["bufferView"]]
        fmt, size = _COMPONENT[accessor["componentType"]]
        width = _COMPONENTS[accessor["type"]]
        stride = view.get("byteStride") or size * width
        start = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
        unpack = struct.Struct("<" + fmt * width).unpack_from
        return [unpack(self.binary, start + i * stride) for i in range(accessor["count"])]

    def _primitive(self, primitive: dict, matrix) -> None:
        if primitive.get("mode", _TRIANGLES) != _TRIANGLES:
            return
        position = primitive.get("attributes", {}).get("POSITION")
        if position is None:
            return
        base = len(self.vertices)
        for x, y, z in self._accessor(position):
            px = matrix[0] * x + matrix[4] * y + matrix[8] * z + matrix[12]
            py = matrix[1] * x + matrix[5] * y + matrix[9] * z + matrix[13]
            pz = matrix[2] * x + matrix[6] * y + matrix[10] * z + matrix[14]
            self.vertices.append((px, -pz, py) if self.z_up else (px, py, pz))
        count = len(self.vertices) - base
        if "indices" in primitive:
            order = [i[0] for i in self._accessor(primitive["indices"])]
        else:
            order = list(range(count))
        for k in range(0, len(order) - len(order) % 3, 3):
            self.faces.append((base + order[k], base + order[k + 1], base + order[k + 2]))
