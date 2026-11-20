import json
import struct

import pytest

from core import meshio
from core.meshes import Mesh


def write_glb(path, document, binary):
    text = json.dumps(document).encode()
    text += b" " * (-len(text) % 4)
    binary += b"\0" * (-len(binary) % 4)
    total = 12 + 8 + len(text) + 8 + len(binary)
    path.write_bytes(
        struct.pack("<III", 0x46546C67, 2, total)
        + struct.pack("<II", len(text), 0x4E4F534A) + text
        + struct.pack("<II", len(binary), 0x004E4942) + binary)


def triangle_document(nodes, indexed=True):
    positions = struct.pack("<9f", 0, 0, 0, 1, 0, 0, 0, 0, -1)
    indices = struct.pack("<3H", 0, 1, 2)
    binary = positions + indices
    views = [{"buffer": 0, "byteOffset": 0, "byteLength": 36}]
    accessors = [{"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3"}]
    primitive = {"attributes": {"POSITION": 0}}
    if indexed:
        views.append({"buffer": 0, "byteOffset": 36, "byteLength": 6})
        accessors.append({"bufferView": 1, "componentType": 5123, "count": 3, "type": "SCALAR"})
        primitive["indices"] = 1
    return {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0]}], "nodes": nodes,
            "meshes": [{"primitives": [primitive]}], "bufferViews": views,
            "accessors": accessors, "buffers": [{"byteLength": len(binary)}]}, binary


def test_obj_reads_vertices_and_faces_with_slashes_and_negative_indices(tmp_path):
    path = tmp_path / "m.obj"
    path.write_text("# c\no a\nv 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\nvt 0 0\nvn 0 0 1\n"
                    "f 1/1/1 2/1/1 3/1/1 4/1/1\nf -4 -3 -2\n", encoding="utf-8")
    mesh = meshio.read_obj(path)
    assert isinstance(mesh, Mesh)
    assert mesh.vertices[2] == (1.0, 1.0, 0.0)
    assert mesh.faces == ((0, 1, 2, 3), (0, 1, 2))
    assert meshio.read_mesh(path) == mesh


def test_obj_write_read_round_trip(tmp_path):
    mesh = Mesh(((0.0, 0.0, 0.0), (0.5, 0.25, 1.0), (0.0, 1.0, 0.125)), ((0, 1, 2),))
    meshio.write_obj(tmp_path / "x.obj", mesh)
    assert meshio.read_obj(tmp_path / "x.obj") == mesh
    low, high = meshio.bounds(mesh)
    assert low == (0.0, 0.0, 0.0) and high == (0.5, 1.0, 1.0)


def test_glb_triangle_is_read_and_converted_to_z_up(tmp_path):
    document, binary = triangle_document([{"mesh": 0}])
    write_glb(tmp_path / "t.glb", document, binary)
    mesh = meshio.read_glb(tmp_path / "t.glb")
    assert mesh.faces == ((0, 1, 2),)
    assert mesh.vertices == ((0, 0, 0), (1, 0, 0), (0, 1, 0))  # glTF (0, 0, -1) -> (0, 1, 0)
    raw = meshio.read_glb(tmp_path / "t.glb", z_up=False)
    assert raw.vertices[2] == (0, 0, -1)
    assert meshio.read_mesh(tmp_path / "t.glb") == mesh


def test_glb_node_transforms_are_applied_through_the_hierarchy(tmp_path):
    half = 0.7071067811865476
    nodes = [{"translation": [10, 0, 0], "scale": [2, 2, 2], "children": [1]},
             {"mesh": 0, "translation": [0, 5, 0], "rotation": [0, 0, half, half]}]
    document, binary = triangle_document(nodes)
    write_glb(tmp_path / "t.glb", document, binary)
    mesh = meshio.read_glb(tmp_path / "t.glb", z_up=False)
    # child: rotate 90 deg about z (x -> y), then +5 in y, then parent scale 2 and +10 in x
    expected = [(10, 10, 0), (10, 12, 0), (10, 10, -2)]
    for got, want in zip(mesh.vertices, expected):
        assert got == pytest.approx(want, abs=1e-9)


def test_glb_matrix_node_and_non_indexed_primitive(tmp_path):
    matrix = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 3, 0, 0, 1]
    document, binary = triangle_document([{"mesh": 0, "matrix": matrix}], indexed=False)
    write_glb(tmp_path / "t.glb", document, binary)
    mesh = meshio.read_glb(tmp_path / "t.glb", z_up=False)
    assert mesh.faces == ((0, 1, 2),) and mesh.vertices[1] == (4, 0, 0)


def test_glb_rejects_garbage(tmp_path):
    (tmp_path / "bad.glb").write_bytes(b"not a glb file at all, really")
    with pytest.raises(ValueError):
        meshio.read_glb(tmp_path / "bad.glb")
    with pytest.raises(ValueError):
        meshio.read_mesh(tmp_path / "model.stl")
