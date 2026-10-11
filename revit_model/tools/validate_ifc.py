import sys, collections, ifcopenshell, ifcopenshell.validate, ifcopenshell.geom, numpy as np, json
f = ifcopenshell.open(sys.argv[1])
logger = ifcopenshell.validate.json_logger()
ifcopenshell.validate.validate(f, logger, express_rules=False)
print('schema issues:', len(logger.statements))
for s in logger.statements[:15]: print('  ', str(s)[:300])
st = ifcopenshell.geom.settings()
st.set('use-world-coords', True)
it = ifcopenshell.geom.iterator(st, f, 4)
ok = collections.Counter(); tris = []
if it.initialize():
    while True:
        sh = it.get()
        el = f.by_id(sh.id)
        g = sh.geometry
        v = np.array(g.verts).reshape(-1, 3); fa = np.array(g.faces).reshape(-1, 3)
        mids = np.array(g.material_ids)
        cols = [m.diffuse.r() if hasattr(m.diffuse, 'r') else 0 for m in g.materials]
        ok[el.is_a()] += 1
        tris.append((el.is_a(), el.Name, v, fa, [(m.diffuse.r(), m.diffuse.g(), m.diffuse.b(), m.transparency) for m in g.materials], mids))
        if not it.next(): break
print('geometry built:', sum(ok.values()), dict(ok))
prods = [p for p in f.by_type('IfcProduct') if p.Representation and not p.is_a('IfcGrid')]
print('products with representation:', len(prods))
import pickle; pickle.dump(tris, open(sys.argv[2], 'wb'))
allv = np.vstack([t[2] for t in tris]); print('bbox', allv.min(0).round(2), allv.max(0).round(2))
