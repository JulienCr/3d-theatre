from collections import Counter

from core.layout import compute_layout
from core.meshes import build_mesh
from core.params import default_params


def make(**groups):
    """Defaults with per-group overrides, e.g. make(stage={"width": 12.0})."""
    params = default_params()
    for key, values in groups.items():
        params[key].update(values)
    return params


def layout(**groups):
    return compute_layout(make(**groups))


def modules_off(params):
    params["modules"]["left"]["enabled"] = False
    params["modules"]["right"]["enabled"] = False
    return params


def bounds(layout_, name):
    verts = build_mesh(layout_.find(name)).vertices
    return tuple((min(v[i] for v in verts), max(v[i] for v in verts)) for i in range(3))


def approx_bounds(actual, expected, tol=1e-9):
    return all(abs(a - e) <= tol for pair, exp in zip(actual, expected) for a, e in zip(pair, exp))


def edge_report(mesh):
    """(open_edges, duplicated_edges): a watertight oriented mesh has none of either."""
    directed = Counter()
    for face in mesh.faces:
        for a, b in zip(face, face[1:] + face[:1]):
            directed[(a, b)] += 1
    open_edges = sum(1 for (a, b) in directed if (b, a) not in directed)
    duplicated = sum(1 for n in directed.values() if n > 1)
    return open_edges, duplicated


def signed_volume(mesh):
    total = 0.0
    for face in mesh.faces:
        p0 = mesh.vertices[face[0]]
        for i in range(1, len(face) - 1):
            p1, p2 = mesh.vertices[face[i]], mesh.vertices[face[i + 1]]
            total += (p0[0] * (p1[1] * p2[2] - p1[2] * p2[1])
                      - p0[1] * (p1[0] * p2[2] - p1[2] * p2[0])
                      + p0[2] * (p1[0] * p2[1] - p1[1] * p2[0])) / 6.0
    return total
