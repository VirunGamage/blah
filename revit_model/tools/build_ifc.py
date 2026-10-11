"""Generate an IFC4 building model (Revit-openable) from model.json."""
import json, math, sys, datetime
import ifcopenshell, ifcopenshell.guid
import ifcopenshell.api.root as root, ifcopenshell.api.unit as unit, ifcopenshell.api.context as context
import ifcopenshell.api.aggregate as aggregate, ifcopenshell.api.spatial as spatial, ifcopenshell.api.style as style
import ifcopenshell.api.material as material, ifcopenshell.api.pset as pset, ifcopenshell.api.project as project

m = json.load(open(sys.argv[1])); OUT = sys.argv[2]
f = ifcopenshell.api.project.create_file(version='IFC4')
proj = root.create_entity(f, 'IfcProject', name='Entertainment Complex - Dewata, Galle')
proj.Description = 'Cinema / entertainment complex modelled from Concept_Desg2 (1).dwg'
lu = unit.add_si_unit(f, unit_type='LENGTHUNIT'); au = unit.add_si_unit(f, unit_type='AREAUNIT')
vu = unit.add_si_unit(f, unit_type='VOLUMEUNIT'); pu = unit.add_si_unit(f, unit_type='PLANEANGLEUNIT')
unit.assign_unit(f, units=[lu, au, vu, pu])
mctx = context.add_context(f, context_type='Model')
BODY = context.add_context(f, context_type='Model', context_identifier='Body', target_view='MODEL_VIEW', parent=mctx)
AXIS = context.add_context(f, context_type='Model', context_identifier='Axis', target_view='GRAPH_VIEW', parent=mctx)
site = root.create_entity(f, 'IfcSite', name='Plot - Dewata, Galle (1 acre, 80 x 50 m)')
bldg = root.create_entity(f, 'IfcBuilding', name='Entertainment Complex')
aggregate.assign_object(f, products=[site], relating_object=proj)
aggregate.assign_object(f, products=[bldg], relating_object=site)

def pt3(x, y, z=0.0): return f.createIfcCartesianPoint((float(x), float(y), float(z)))
def pt2(x, y): return f.createIfcCartesianPoint((float(x), float(y)))
def d3(x, y, z): return f.createIfcDirection((float(x), float(y), float(z)))
def ax3(o=(0, 0, 0), z=(0, 0, 1), x=(1, 0, 0)): return f.createIfcAxis2Placement3D(pt3(*o), d3(*z), d3(*x))
def lplace(rel, o=(0, 0, 0), x=(1, 0, 0)): return f.createIfcLocalPlacement(rel, ax3(o, (0, 0, 1), x))

site.ObjectPlacement = lplace(None)
bldg.ObjectPlacement = lplace(site.ObjectPlacement)
STOREY = {}
for L in m['levels']:
    s = root.create_entity(f, 'IfcBuildingStorey', name=L['name'])
    s.Elevation = L['elev']; s.Description = L['use']; s.LongName = '%s (+%.2f m)' % (L['name'], L['elev'])
    s.ObjectPlacement = lplace(bldg.ObjectPlacement, (0, 0, L['elev']))
    STOREY[L['id']] = (s, L['elev'])
aggregate.assign_object(f, products=[s for s, _ in STOREY.values()], relating_object=bldg)

# ------------------------------------------------------------------ styles & materials
STY = {}; MAT = {}
def mkstyle(name, rgb, transp=0.0):
    st = style.add_style(f, name=name)
    style.add_surface_style(f, style=st, ifc_class='IfcSurfaceStyleShading',
                            attributes={'SurfaceColour': {'Name': None, 'Red': rgb[0], 'Green': rgb[1], 'Blue': rgb[2]}, 'Transparency': transp})
    STY[name] = st
    MAT[name] = material.add_material(f, name=name, category={'Concrete': 'concrete', 'Glass': 'glass', 'Steel': 'steel'}.get(name.split()[0], None))
for n, c, t in [('Concrete', (0.75, 0.75, 0.73), 0), ('Blockwork', (0.93, 0.90, 0.84), 0), ('Glass', (0.55, 0.75, 0.90), 0.6),
                ('Glass facade', (0.35, 0.55, 0.75), 0.45), ('Asphalt drive aisle', (0.33, 0.36, 0.38), 0), ('Parking bay paint', (0.80, 0.86, 0.95), 0),
                ('Ramp concrete', (0.95, 0.80, 0.35), 0), ('Steel escalator', (0.55, 0.58, 0.62), 0), ('Lift car', (0.80, 0.80, 0.85), 0),
                ('Seat fabric', (0.70, 0.08, 0.10), 0), ('Stadium riser', (0.35, 0.18, 0.15), 0), ('Screen', (0.98, 0.98, 0.98), 0),
                ('Paving', (0.62, 0.62, 0.60), 0), ('Roof', (0.70, 0.72, 0.75), 0), ('Door', (0.55, 0.38, 0.20), 0), ('Space', (0.6, 0.9, 0.6), 0.85)]:
    mkstyle(n, c, t)

# ------------------------------------------------------------------ geometry helpers
def polyline2(pts):
    pts = [tuple(p) for p in pts]
    if pts[0] != pts[-1]: pts = pts + [pts[0]]
    return f.createIfcPolyline([pt2(*p) for p in pts])

def signed_area(pts):
    return sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1] for i in range(len(pts))) / 2

def ccw(pts, want=True):
    pts = [tuple(p) for p in pts]
    return pts if (signed_area(pts) > 0) == want else pts[::-1]

def profile(outer, holes=()):
    o = polyline2(ccw(outer, True))
    if holes:
        return f.createIfcArbitraryProfileDefWithVoids('AREA', None, o, [polyline2(ccw(h, False)) for h in holes])
    return f.createIfcArbitraryClosedProfileDef('AREA', None, o)

def extrude(outer, depth, z0=0.0, holes=(), position=None):
    return f.createIfcExtrudedAreaSolid(profile(outer, holes), position or ax3((0, 0, z0)), d3(0, 0, 1), float(depth))

def vextrude(prof_pts, origin, t, n, width):
    """Extrude a profile drawn in a vertical plane: local x = travel dir t, local y = up, extruded along n by width."""
    pos = ax3(origin, n, t)
    return f.createIfcExtrudedAreaSolid(profile(prof_pts), pos, d3(0, 0, 1), float(width))

def brep(faces):
    fs = []
    for poly in faces:
        fs.append(f.createIfcFace([f.createIfcFaceOuterBound(f.createIfcPolyLoop([pt3(*p) for p in poly]), True)]))
    return f.createIfcFacetedBrep(f.createIfcClosedShell(fs))

def shape(items, kind='SweptSolid', sty=None, axis_pts=None):
    for it in items:
        if sty: style.assign_item_style(f, item=it, style=STY[sty])
    reps = [f.createIfcShapeRepresentation(BODY, 'Body', kind, items)]
    if axis_pts:
        reps.insert(0, f.createIfcShapeRepresentation(AXIS, 'Axis', 'Curve2D', [f.createIfcPolyline([pt2(*p) for p in axis_pts])]))
    return f.createIfcProductDefinitionShape(None, None, reps)

PRODUCTS = {}
def product(cls, name, level, items, kind='SweptSolid', sty=None, ptype=None, otype=None, place=None, axis_pts=None, mat=None, desc=None):
    e = root.create_entity(f, cls, name=name, predefined_type=ptype)
    if otype: e.ObjectType = otype
    if desc: e.Description = desc
    st, elev = STOREY[level]
    e.ObjectPlacement = place if place is not None else lplace(st.ObjectPlacement)
    e.Representation = shape(items, kind, sty, axis_pts)
    PRODUCTS.setdefault(level, []).append(e)
    if mat or sty:
        MATLIST.setdefault(mat or sty, []).append(e)
    return e
MATLIST = {}

def zrel(level, z): return z - STOREY[level][1]

# ------------------------------------------------------------------ walls
for w in m['walls']:
    (x0, y0), (x1, y1) = w['p0'], w['p1']
    L = math.hypot(x1 - x0, y1 - y0); t = w['thk']
    if L < 0.05: continue
    ux, uy = (x1 - x0) / L, (y1 - y0) / L
    pl = lplace(STOREY[w['level']][0].ObjectPlacement, (x0, y0, w['base']), (ux, uy, 0))
    body = extrude([(0, -t / 2), (L, -t / 2), (L, t / 2), (0, t / 2)], w['h'])
    if w['kind'] == 'curtain':
        product('IfcCurtainWall', w['name'], w['level'], [body], sty='Glass facade', place=pl, axis_pts=[(0, 0), (L, 0)])
    else:
        ptype = {'masonry': 'STANDARD', 'glazed': 'PARTITIONING', 'parapet': 'PARAPET'}[w['kind']]
        sty = {'masonry': 'Blockwork', 'glazed': 'Glass', 'parapet': 'Blockwork'}[w['kind']]
        product('IfcWall', w['name'], w['level'], [body], sty=sty, ptype=ptype, place=pl, axis_pts=[(0, 0), (L, 0)])

def sector(c, r0, r1, a0, a1, n=24):
    A = [math.radians(a0 + (a1 - a0) * i / n) for i in range(n + 1)]
    return [(c[0] + r0 * math.cos(a), c[1] + r0 * math.sin(a)) for a in A] + [(c[0] + r1 * math.cos(a), c[1] + r1 * math.sin(a)) for a in A[::-1]]

for w in m['arc_walls']:
    body = extrude(sector(w['center'], w['r'] - w['thk'] / 2, w['r'] + w['thk'] / 2, w['a0'], w['a1']), w['h'])
    product('IfcWall', w['name'], w['level'], [body], sty='Glass', ptype='PARTITIONING')

for r in m['railings']:
    (x0, y0), (x1, y1) = r['p0'], r['p1']
    L = math.hypot(x1 - x0, y1 - y0)
    if L < 0.05: continue
    ux, uy = (x1 - x0) / L, (y1 - y0) / L
    pl = lplace(STOREY[r['level']][0].ObjectPlacement, (x0, y0, 0), (ux, uy, 0))
    product('IfcRailing', r['name'], r['level'], [extrude([(0, -0.03), (L, -0.03), (L, 0.03), (0, 0.03)], r['h'])], sty='Glass', ptype='BALUSTRADE', place=pl)

# ------------------------------------------------------------------ columns
for c in m['columns']:
    hw, hd = c['w'] / 2, c['d'] / 2
    pl = lplace(STOREY[c['level']][0].ObjectPlacement, (c['x'], c['y'], 0))
    product('IfcColumn', 'Column 600x600', c['level'], [extrude([(-hw, -hd), (hw, -hd), (hw, hd), (-hw, hd)], c['h'])],
            sty='Concrete', ptype='COLUMN', place=pl)

# ------------------------------------------------------------------ slabs & surfaces
for s in m['slabs']:
    z_top = zrel(s['level'], s['top'])
    body = extrude(s['outer'], s['thk'], z_top - s['thk'], s['holes'])
    ptype = 'ROOF' if s['kind'] == 'roof' else ('BASESLAB' if s['level'] == 'L00' else 'FLOOR')
    product('IfcSlab', s['name'], s['level'], [body], sty={'ROOF': 'Roof', 'BASESLAB': 'Paving', 'FLOOR': 'Concrete'}[ptype], ptype=ptype)

for s in m['surfaces']:
    product('IfcCovering', s['name'], s['level'], [extrude(s['poly'], s['thk'], 0.0)], sty='Asphalt drive aisle', ptype='FLOORING', otype='Vehicle circulation')

for i, b in enumerate(m['parking_bays']):
    pts = b['poly']; cx = sum(p[0] for p in pts) / 4; cy = sum(p[1] for p in pts) / 4
    ins = [(cx + (p[0] - cx) * 0.96, cy + (p[1] - cy) * 0.985) for p in pts]
    product('IfcBuildingElementProxy', 'Parking stall', b['level'], [extrude(ins, 0.025, 0.0)], sty='Parking bay paint',
            otype='Parking stall 2.4-2.5 x 5.0 m')

# ------------------------------------------------------------------ ramps (helical J segment) with kerbs
def ramp_sections(r, n_arc=24):
    C = r['center']; rin, rout, rox = r['r_in'], r['r_out'], r['r_out_x']
    L1 = C[1] - r['y_start']; La = math.pi / 2 * r['r_cl']; L2 = C[0] - r['x_end']; LT = L1 + La + L2
    secs = []   # (inner_xy, outer_xy, s)
    for k in range(3):
        y = r['y_start'] + L1 * k / 2
        secs.append(((C[0] + rin, y), (C[0] + rox, y), L1 * k / 2))
    for i in range(1, n_arc + 1):
        a = math.pi / 2 * i / n_arc
        secs.append(((C[0] + rin * math.cos(a), C[1] + rin * math.sin(a)), (C[0] + rox * math.cos(a), C[1] + rout * math.sin(a)), L1 + La * i / n_arc))
    for k in range(1, 3):
        x = C[0] - L2 * k / 2
        secs.append(((x, C[1] + rin), (x, C[1] + rout), L1 + La + L2 * k / 2))
    return secs, LT

def band_brep(secs3):
    """secs3: list of (a_xy, b_xy, z_bot, z_top) cross-sections -> closed faceted brep (triangulated)."""
    faces = []
    n = len(secs3)
    def P(i, side, top):
        a, b, zb, zt = secs3[i]
        xy = a if side == 0 else b
        return (xy[0], xy[1], zt if top else zb)
    for i in range(n - 1):
        # top (two triangles), bottom, side a, side b
        faces += [[P(i, 0, 1), P(i, 1, 1), P(i + 1, 1, 1)], [P(i, 0, 1), P(i + 1, 1, 1), P(i + 1, 0, 1)]]
        faces += [[P(i, 0, 0), P(i + 1, 1, 0), P(i, 1, 0)], [P(i, 0, 0), P(i + 1, 0, 0), P(i + 1, 1, 0)]]
        faces += [[P(i, 0, 0), P(i, 0, 1), P(i + 1, 0, 1), P(i + 1, 0, 0)]]
        faces += [[P(i, 1, 0), P(i + 1, 1, 0), P(i + 1, 1, 1), P(i, 1, 1)]]
    faces += [[P(0, 0, 0), P(0, 1, 0), P(0, 1, 1), P(0, 0, 1)]]
    faces += [[P(n - 1, 0, 0), P(n - 1, 0, 1), P(n - 1, 1, 1), P(n - 1, 1, 0)]]
    return brep(faces)

def lerp(a, b, t): return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)

for r in m['ramps']:
    lvl = r['from_level']; base = STOREY[lvl][1]
    secs, LT = ramp_sections(r)
    z = lambda s: r['z0'] + (r['z1'] - r['z0']) * s / LT - base
    slab = band_brep([(a, b, z(s) - r['thk'], z(s)) for a, b, s in secs])
    ramp = root.create_entity(f, 'IfcRamp', name=r['name'], predefined_type='HALF_TURN_RAMP')
    ramp.Description = 'Two-lane 6.0 m J-shaped car ramp, centre-line %.2f m, slope %.1f %%' % (r['centerline_length'], r['slope_pct'])
    ramp.ObjectPlacement = lplace(STOREY[lvl][0].ObjectPlacement)
    PRODUCTS.setdefault(lvl, []).append(ramp)
    fl = product('IfcRampFlight', r['name'] + ' - flight', lvl, [slab], kind='Brep', sty='Ramp concrete', ptype='SPIRAL')
    PRODUCTS[lvl].remove(fl)
    parts = [fl]
    for side, nm in [(0, 'inner'), (1, 'outer')]:
        ks = []
        for a, b, s in secs:
            e0 = a if side == 0 else b
            e1 = lerp(e0, b if side == 0 else a, 0.2 / math.hypot(b[0] - a[0], b[1] - a[1]))
            ks.append((e0, e1, z(s), z(s) + r['kerb_h']))
        k = product('IfcRailing', r['name'] + ' - %s kerb wall' % nm, lvl, [band_brep(ks)], kind='Brep', sty='Concrete', ptype='GUARDRAIL')
        PRODUCTS[lvl].remove(k); parts.append(k)
    aggregate.assign_object(f, products=parts, relating_object=ramp)
    for e in parts: e.ObjectPlacement = lplace(ramp.ObjectPlacement)
    pset.edit_pset(f, pset=pset.add_pset(f, product=ramp, name='Pset_RampCommon'),
                   properties={'RequiredSlope': math.atan((r['z1'] - r['z0']) / r['centerline_length']), 'IsExternal': False})

# ------------------------------------------------------------------ stairs
for st in m['stairs']:
    lvl = st['from_level']; base = STOREY[lvl][1]
    stair = root.create_entity(f, 'IfcStair', name=st['name'], predefined_type='HALF_TURN_STAIR')
    stair.Description = '%d risers x %.0f mm, going %.0f mm' % (st['risers'], st['riser'] * 1000, st['tread'] * 1000)
    stair.ObjectPlacement = lplace(STOREY[lvl][0].ObjectPlacement)
    PRODUCTS.setdefault(lvl, []).append(stair)
    parts = []
    for fl in st['flights']:
        n = fl['risers']; rh = (fl['z1'] - fl['z0']) / n; t = st['tread']; run = (n - 1) * t
        prof = [(0.0, 0.0)]
        for k in range(n):
            prof.append((k * t, (k + 1) * rh))
            if k < n - 1: prof.append(((k + 1) * t, (k + 1) * rh))
        d = 0.22
        u0 = run - (n * rh - d) * t / rh
        prof += [(run, n * rh - d), (max(u0, 0.05), 0.0)]
        tx = 1.0 if fl['x_high'] > fl['x_low'] else -1.0
        tvec = (tx, 0, 0); nvec = (0, -tx, 0)
        oy = fl['y1'] if nvec[1] < 0 else fl['y0']
        solid = vextrude(prof, (fl['x_low'], oy, fl['z0'] - base), tvec, nvec, fl['y1'] - fl['y0'])
        e = product('IfcStairFlight', st['name'] + ' - flight', lvl, [solid], sty='Concrete', ptype='STRAIGHT')
        PRODUCTS[lvl].remove(e); parts.append(e)
    ld = st['landing']
    e = product('IfcSlab', st['name'] + ' - half landing', lvl,
                [extrude([(ld['x0'], ld['y0']), (ld['x1'], ld['y0']), (ld['x1'], ld['y1']), (ld['x0'], ld['y1'])], ld['thk'], ld['z'] - base - ld['thk'])],
                sty='Concrete', ptype='LANDING')
    PRODUCTS[lvl].remove(e); parts.append(e)
    aggregate.assign_object(f, products=parts, relating_object=stair)
    for e in parts: e.ObjectPlacement = lplace(stair.ObjectPlacement)
    pset.edit_pset(f, pset=pset.add_pset(f, product=stair, name='Pset_StairCommon'),
                   properties={'NumberOfRiser': st['risers'], 'NumberOfTreads': st['risers'] - 2, 'RiserHeight': st['riser'], 'TreadLength': st['tread']})

# ------------------------------------------------------------------ escalators
for e_ in m['escalators']:
    lvl = e_['from_level']; base = STOREY[lvl][1]
    H = e_['z1'] - e_['z0']; Lp = e_['a1'] - e_['a0']; Li = H / math.tan(math.radians(e_['angle'])); lb = (Lp - Li) / 2
    bottom = e_['a1'] if e_['bottom_end'] == 'max' else e_['a0']; sgn = -1.0 if e_['bottom_end'] == 'max' else 1.0
    if e_['axis'] == 'y':
        tvec = (0, sgn, 0); nvec = (sgn, 0, 0)          # n = (t_y, -t_x, 0)
        ox = e_['b0'] if nvec[0] > 0 else e_['b1']; origin = (ox, bottom, 0.0)
    else:
        tvec = (sgn, 0, 0); nvec = (0, -sgn, 0)
        oy = e_['b0'] if nvec[1] > 0 else e_['b1']; origin = (bottom, oy, 0.0)
    W = e_['b1'] - e_['b0']
    truss = [(0, 0), (lb, 0), (lb + Li, H), (Lp, H), (Lp, H - 1.0), (lb + Li, H - 1.0), (lb, -1.0), (0, -1.0)]
    truss = [(u, v) for u, v in truss]
    o = (origin[0], origin[1], e_['z0'] - base)
    items = [vextrude(truss, o, tvec, nvec, W)]
    bal = [(lb * 0.5, 0.0), (lb, 0.0), (lb + Li, H), (Lp - lb * 0.5, H), (Lp - lb * 0.5, H + 1.0), (lb + Li, H + 1.0), (lb, 1.0), (lb * 0.5, 1.0)]
    for off in (0.0, W - 0.05):
        oo = (o[0] + nvec[0] * off, o[1] + nvec[1] * off, o[2])
        items.append(vextrude(bal, oo, tvec, nvec, 0.05))
    product('IfcTransportElement', e_['name'], lvl, items, sty='Steel escalator', ptype='ESCALATOR',
            desc='Rise %.1f m at 30 deg, plan length %.1f m, width %.2f m' % (H, Lp, W))

# ------------------------------------------------------------------ lifts
DOOR_W, DOOR_H = 1.1, 2.1
storeys = [L for L in m['levels'] if L['id'] != 'L06']
def wall_box(level, x0, y0, x1, y1, z0, z1, name, sty='Concrete', cls='IfcWall', ptype='SHEAR'):
    if x1 - x0 < 0.02 or y1 - y0 < 0.02 or z1 - z0 < 0.02: return
    product(cls, name, level, [extrude([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], z1 - z0, z0 - STOREY[level][1])], sty=sty, ptype=ptype)

for b in m['lift_banks']:
    X0, Y0, X1, Y1 = b['outer']; t = b['wall_t']; ztop = b['z1']; nm = b['name'] + ' - shaft wall'
    cars = b['cars']
    if b['door_side'] == 'S':
        wall_box('L00', X0, Y1 - t, X1, Y1, 0, ztop, nm)                      # back
        wall_box('L00', X0, Y0, X0 + t, Y1 - t, 0, ztop, nm)                  # west
        wall_box('L00', X1 - t, Y0, X1, Y1 - t, 0, ztop, nm)                  # east
        for i in range(len(cars) - 1):
            wall_box('L00', cars[i][2], Y0 + t, cars[i + 1][0], Y1 - t, 0, ztop, nm)
        spans = [((c[0] + c[2]) / 2 - DOOR_W / 2, (c[0] + c[2]) / 2 + DOOR_W / 2) for c in cars]
        front = lambda lv, a0, a1, z0, z1: wall_box(lv, a0, Y0, a1, Y0 + t, z0, z1, nm)
        lo, hi = X0 + t, X1 - t
    else:  # 'E'
        wall_box('L00', X0, Y0, X0 + t, Y1, 0, ztop, nm)                      # west (back)
        wall_box('L00', X0 + t, Y0, X1 - t, Y0 + t, 0, ztop, nm)              # south
        wall_box('L00', X0 + t, Y1 - t, X1 - t, Y1, 0, ztop, nm)              # north
        for i in range(len(cars) - 1):
            wall_box('L00', X0 + t, cars[i][3], X1 - t, cars[i + 1][1], 0, ztop, nm)
        spans = [((c[1] + c[3]) / 2 - DOOR_W / 2, (c[1] + c[3]) / 2 + DOOR_W / 2) for c in cars]
        front = lambda lv, a0, a1, z0, z1: wall_box(lv, X1 - t, a0, X1, a1, z0, z1, nm)
        lo, hi = Y0, Y1
    for L in storeys:
        z0 = L['elev']; z1 = z0 + L['height']
        edges = [lo] + [v for sp in spans for v in sp] + [hi]
        for i in range(0, len(edges), 2):
            front(L['id'], edges[i], edges[i + 1], z0, z1)
        for a0, a1 in spans:
            front(L['id'], a0, a1, z0 + DOOR_H, z1)
            if b['door_side'] == 'S':
                dpts = [(a0, Y0 + t / 2 - 0.03), (a1, Y0 + t / 2 - 0.03), (a1, Y0 + t / 2 + 0.03), (a0, Y0 + t / 2 + 0.03)]
            else:
                dpts = [(X1 - t / 2 - 0.03, a0), (X1 - t / 2 + 0.03, a0), (X1 - t / 2 + 0.03, a1), (X1 - t / 2 - 0.03, a1)]
            product('IfcDoor', b['name'] + ' - landing door', L['id'], [extrude(dpts, DOOR_H, 0.0)], sty='Steel escalator', ptype='DOOR',
                    otype='Lift landing door 1100 x 2100')
    zt = m['levels'][-1]['elev']
    front('L06', lo, hi, zt, ztop)
    for i, c in enumerate(cars):
        product('IfcTransportElement', '%s - lift car %d' % (b['name'], i + 1), 'L00',
                [extrude([(c[0] + 0.1, c[1] + 0.1), (c[2] - 0.1, c[1] + 0.1), (c[2] - 0.1, c[3] - 0.1), (c[0] + 0.1, c[3] - 0.1)], 2.4, 0.05)],
                sty='Lift car', ptype='ELEVATOR', desc='Passenger lift, car %.1f x %.1f m, serves ground to third floor' % (c[2] - c[0], c[3] - c[1]))

# ------------------------------------------------------------------ doors
for d in m['doors']:
    x, y = d['p']; w = d['w']
    if d['axis'] == 'y':
        pts = [(x - 0.03, y - w / 2), (x + 0.03, y - w / 2), (x + 0.03, y + w / 2), (x - 0.03, y + w / 2)]
    else:
        pts = [(x - w / 2, y - 0.03), (x + w / 2, y - 0.03), (x + w / 2, y + 0.03), (x - w / 2, y + 0.03)]
    e = product('IfcDoor', d['name'], d['level'], [extrude(pts, d['h'], 0.0)], sty='Door', ptype='DOOR')
    e.OverallWidth = w; e.OverallHeight = d['h']
    e.OperationType = 'DOUBLE_DOOR_SINGLE_SWING' if d['leaves'] == 2 else 'SINGLE_SWING_RIGHT'

# ------------------------------------------------------------------ cinema
for r in m['risers']:
    product('IfcSlab', 'Stadium seating riser - %s row %d' % (r['theatre'], r['row']), r['level'],
            [extrude(r['poly'], r['z1'] - r['z0'], zrel(r['level'], r['z0']))], sty='Stadium riser', ptype='NOTDEFINED', otype='Stadium seating riser')
for s in m['seats']:
    a = math.radians(s['rot'])
    pl = lplace(STOREY[s['level']][0].ObjectPlacement, (s['x'], s['y'], zrel(s['level'], s['z'])), (math.cos(a), math.sin(a), 0))
    seat = extrude([(-0.62, -0.26), (-0.12, -0.26), (-0.12, 0.26), (-0.62, 0.26)], 0.46, 0.0)
    back = extrude([(-0.16, -0.27), (0.0, -0.27), (0.0, 0.27), (-0.16, 0.27)], 1.0, 0.0)
    arms = extrude([(-0.62, 0.26), (-0.05, 0.26), (-0.05, 0.30), (-0.62, 0.30)], 0.65, 0.0)
    product('IfcFurniture', 'Cinema seat - %s row %d' % (s['theatre'], s['row']), s['level'], [seat, back, arms], sty='Seat fabric',
            ptype='CHAIR', place=pl)
for s in m['screens']:
    body = extrude(sector(s['center'], s['r'], s['r'] + s['thk'], s['a0'], s['a1']), s['h'], zrel(s['level'], s['z0']))
    product('IfcBuildingElementProxy', s['name'], s['level'], [body], sty='Screen', otype='Cinema screen (curved)',
            desc='Faces the seating of %s' % s['theatre'])

# ------------------------------------------------------------------ spaces
for sp in m['spaces']:
    e = root.create_entity(f, 'IfcSpace', name=sp['name'], predefined_type='INTERNAL')
    e.LongName = sp['name']
    e.ObjectPlacement = lplace(STOREY[sp['level']][0].ObjectPlacement)
    e.Representation = shape([extrude(sp['poly'], sp['h'] - 0.05, 0.0)], sty='Space')
    aggregate.assign_object(f, products=[e], relating_object=STOREY[sp['level']][0])

# ------------------------------------------------------------------ grids
gx = [0.0, 8.0, 16.0, 24.0, 32.0, 40.0, 48.0, 56.0, 64.0, 73.9]
gy = [('A', -8.0), ('B', 0.0), ('C', 8.0), ('D', 18.0), ('E', 25.9), ('F', 33.9)]
U = [f.createIfcGridAxis(str(i + 1), f.createIfcPolyline([pt2(x, -13.0), pt2(x, 39.0)]), True) for i, x in enumerate(gx)]
V = [f.createIfcGridAxis(n, f.createIfcPolyline([pt2(-5.0, y), pt2(79.0, y)]), True) for n, y in gy]
grid = root.create_entity(f, 'IfcGrid', name='Structural grid')
grid.UAxes = U; grid.VAxes = V
grid.ObjectPlacement = lplace(STOREY['L00'][0].ObjectPlacement)
grid.Representation = f.createIfcProductDefinitionShape(None, None, [f.createIfcShapeRepresentation(
    context.add_context(f, context_type='Model', context_identifier='FootPrint', target_view='PLAN_VIEW', parent=mctx),
    'FootPrint', 'GeometricCurveSet', [f.createIfcGeometricCurveSet([a.AxisCurve for a in U + V])])])
PRODUCTS['L00'].append(grid)

# ------------------------------------------------------------------ containment, materials, notes
for lvl, prods in PRODUCTS.items():
    spatial.assign_container(f, products=prods, relating_structure=STOREY[lvl][0])
for mname, prods in MATLIST.items():
    mat = MAT.get(mname)
    if mat:
        material.assign_material(f, products=prods, type='IfcMaterial', material=mat)
ps = pset.add_pset(f, product=bldg, name='Pset_ModelNotes')
props = {'Source': m['source'], 'Origin': m['origin'], 'Units': 'metres'}
for i, a in enumerate(m['assumptions']):
    props['Note%02d' % (i + 1)] = a
props['ParkingStalls'] = ', '.join('%s=%d' % kv for kv in sorted(m['parking_count'].items()))
props['Theatres'] = '; '.join('%s: %d rows, %d seats, screen side %s' % (v['name'], v['rows'], v['seats'], 'west' if v['faces'] == '-x' else 'south')
                              for v in m['theatres'].values())
pset.edit_pset(f, pset=ps, properties=props)
f.write(OUT)
print('written', OUT, sum(len(v) for v in PRODUCTS.values()), 'products')
