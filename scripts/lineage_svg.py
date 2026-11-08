"""Draw the dbt lineage graph as SVG from target/manifest.json (no graphviz needed).

Usage: python scripts/lineage_svg.py dbt/fhir_analytics/target/manifest.json docs/img/lineage.svg
Run `dbt docs generate` (or `dbt parse`) first.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

LAYERS = ["source", "staging", "intermediate", "marts"]
COLORS = {"source": "#e8eef7", "staging": "#e3f2e6", "intermediate": "#fdf3d9", "marts": "#f6e0e0"}


def layer_of(node_id: str, node: dict) -> str | None:  # type: ignore[type-arg]
    if node_id.startswith("source."):
        return "source"
    if node.get("resource_type") != "model":
        return None
    folder = node["path"].split("/")[0]
    return folder if folder in LAYERS else None


def main(manifest_path: Path, out_path: Path) -> None:
    manifest = json.loads(manifest_path.read_text())
    nodes = {**manifest["sources"], **manifest["nodes"]}
    layer = {i: layer_of(i, n) for i, n in nodes.items() if layer_of(i, n)}
    cols: dict[str, list[str]] = {name: [] for name in LAYERS}
    for node_id, name in sorted(layer.items(), key=lambda kv: nodes[kv[0]]["name"]):
        cols[name or ""].append(node_id)
    w, h, gx, gy, top = 190, 26, 70, 12, 50
    pos = {}
    for ci, name in enumerate(LAYERS):
        for ri, node_id in enumerate(cols[name]):
            pos[node_id] = (20 + ci * (w + gx), top + ri * (h + gy))
    width = 20 + len(LAYERS) * (w + gx)
    height = top + max(len(c) for c in cols.values()) * (h + gy) + 20
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
           f'width="{width}" height="{height}" font-family="sans-serif" font-size="12">',
           '<rect width="100%" height="100%" fill="white"/>']
    for ci, name in enumerate(LAYERS):
        out.append(f'<text x="{20 + ci * (w + gx)}" y="28" font-weight="bold" font-size="14">{name}</text>')
    parents = {i: nodes[i].get("depends_on", {}).get("nodes", []) for i in layer}
    for child, ps in parents.items():
        for p in ps:
            if p in pos:
                x1, y1 = pos[p][0] + w, pos[p][1] + h / 2
                x2, y2 = pos[child][0], pos[child][1] + h / 2
                mid = (x1 + x2) / 2
                out.append(f'<path d="M{x1},{y1} C{mid},{y1} {mid},{y2} {x2},{y2}" fill="none" '
                           'stroke="#9aa5b1" stroke-width="1.2"/>')
    for node_id, (x, y) in pos.items():
        name = nodes[node_id]["name"]
        out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="5" fill="{COLORS[layer[node_id] or ""]}" '
                   'stroke="#6b7785"/>')
        out.append(f'<text x="{x + 8}" y="{y + 17}">{name}</text>')
    out.append("</svg>")
    out_path.write_text("\n".join(out))
    print(f"{len(pos)} nodes, {sum(len(v) for v in parents.values())} edges")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
