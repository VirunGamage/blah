import sys, pickle, numpy as np, trimesh, collections
tris = pickle.load(open(sys.argv[1], 'rb'))
groups = collections.defaultdict(lambda: ([], [], 0))
meshes = collections.defaultdict(list)
for cls, name, v, fa, mats, mids in tris:
    if cls == 'IfcSpace': continue
    for mi in set(mids.tolist()) if len(mids) else [0]:
        sel = fa[mids == mi] if len(mids) else fa
        r, g, b, t = mats[mi] if mats else (0.7, 0.7, 0.7, 0)
        key = (cls, round(r, 3), round(g, 3), round(b, 3), round(t or 0, 2))
        meshes[key].append((v, sel))
scene = trimesh.Scene()
for (cls, r, g, b, t), parts in meshes.items():
    V = []; F = []; off = 0
    for v, fa in parts:
        V.append(v); F.append(fa + off); off += len(v)
    V = np.vstack(V); F = np.vstack(F)
    # IFC is Z-up; glTF is Y-up
    V2 = np.column_stack([V[:, 0], V[:, 2], -V[:, 1]])
    mesh = trimesh.Trimesh(V2, F, process=False)
    alpha = 1.0 - (t or 0)
    mat = trimesh.visual.material.PBRMaterial(baseColorFactor=[r, g, b, alpha], metallicFactor=0.0, roughnessFactor=0.9,
                                              alphaMode='BLEND' if alpha < 0.99 else 'OPAQUE', doubleSided=True)
    mesh.visual = trimesh.visual.TextureVisuals(material=mat)
    scene.add_geometry(mesh, node_name='%s_%d' % (cls, len(scene.geometry)), geom_name='%s_%d' % (cls, len(scene.geometry)))
scene.export(sys.argv[2])
print('ok', len(scene.geometry), 'meshes')
