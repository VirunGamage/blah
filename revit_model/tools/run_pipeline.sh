#!/usr/bin/env bash
# Regenerate every output from the DWG.  Needs: LibreDWG (dwgread), python3 with
# ezdxf, shapely, ifcopenshell (0.8+), numpy, trimesh, matplotlib.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; OUT="$(dirname "$HERE")"; WORK="${WORK:-/tmp/ec_work}"
mkdir -p "$WORK"
cp "$OUT/../Concept_Desg2 (1).dwg" "$WORK/concept.dwg"
dwgread -O JSON -o "$WORK/concept.json" "$WORK/concept.dwg"            # DWG -> JSON (keeps dynamic-block geometry)
python3 "$HERE/dwgflat.py"       "$WORK/concept.json" "$WORK/flat.json"  # expand blocks to world-space primitives
python3 "$HERE/extract_model.py" "$HERE" "$WORK/flat.json" "$OUT/model.json"
python3 "$HERE/build_ifc.py"     "$OUT/model.json" "$OUT/Entertainment_Complex.ifc"
python3 "$HERE/validate_ifc.py"  "$OUT/Entertainment_Complex.ifc" "$WORK/tris.pkl"
python3 "$HERE/to_glb.py"        "$WORK/tris.pkl" "$OUT/Entertainment_Complex.glb"
python3 "$HERE/to_dxf.py"        "$WORK/tris.pkl" "$OUT/Entertainment_Complex_3D.dxf"
python3 "$HERE/plot_model.py"    "$OUT/model.json" "$OUT/previews/plan_check_all_levels.png"
