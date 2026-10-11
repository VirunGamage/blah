"""Build the building model (model.json) from the flattened DWG primitives.

All coordinates are metres in a global system whose origin is grid A1 of the
ground-level parking plan (column at DWG (56.30, 28.12)).  +X runs east along
the 74 m frontage, +Y runs north away from the A2 road.
"""
import json, math, sys, collections
sys.path.insert(0, sys.argv[1])
from walls import segs_from_prims, merge
from shapely.geometry import Polygon, Point, LineString, box
from shapely.ops import unary_union

d = json.load(open(sys.argv[2]))
P = d['prims']
OUT = sys.argv[3]

PLANS = {
    'GF':  {'bbox': (52, 10, 136, 68),  'off': (56.30, 28.12)},
    'P12': {'bbox': (155, 10, 239, 68), 'off': (158.55, 27.81)},
    'FF':  {'bbox': (52, 92, 136, 146), 'off': (57.20, 105.34)},
    'TF':  {'bbox': (148, 92, 232, 146), 'off': (152.25, 105.22)},
}
LEVELS = [
    dict(id='L00', name='Ground Level Parking', elev=0.0, height=3.2, plan='GF', use='Car parking (63 cars noted)'),
    dict(id='L01', name='First Level Parking', elev=3.2, height=3.2, plan='P12', use='Car parking (54 cars)'),
    dict(id='L02', name='Second Level Parking', elev=6.4, height=3.2, plan='P12', use='Car parking (54 cars)'),
    dict(id='L03', name='First Floor', elev=9.6, height=4.2, plan='FF', use='Restaurants, cafeterias, gaming'),
    dict(id='L04', name='Second Floor', elev=13.8, height=4.2, plan='FF', use='Restaurants, cafeterias, gaming'),
    dict(id='L05', name='Third Floor - Cinema', elev=18.0, height=9.0, plan='TF', use='Cinema: 3 theatres (108/200/136 seats)'),
    dict(id='L06', name='Roof', elev=27.0, height=0.0, plan=None, use='Roof'),
]
LV = {l['id']: l for l in LEVELS}

SLAB_T = 0.20          # RC slab thickness (parking + floors + roof)
WALL_T = 0.20          # 200 mm blockwork (drawn as 100 mm double lines in the DWG)
GLAZ_T = 0.10          # glazed shopfront / foyer partitions
CW_T = 0.15            # curtain wall (facade glazing)
PARAPET_H = 1.10
RISER_H = 0.35         # cinema stadium step per seating row
ATRIUM_TOP = 22.0      # glazed atrium box height (front elevation: 22.0 m)

def g(plan, x, y):
    ox, oy = PLANS[plan]['off']
    return (x - ox, y - oy)

def in_bbox(p, bb):
    xs = [q[0] for q in p['pts']]; ys = [q[1] for q in p['pts']]
    return bb[0] <= min(xs) and max(xs) <= bb[2] and bb[1] <= min(ys) and max(ys) <= bb[3]

def plan_prims(plan, layers, top_level_only=True, kinds=('line', 'poly')):
    out = []
    for p in P:
        if p['layer'] not in layers or p['kind'] not in kinds:
            continue
        if top_level_only and p['top_type'] == 'INSERT':
            continue
        if not in_bbox(p, PLANS[plan]['bbox']):
            continue
        out.append(dict(p, pts=[g(plan, x, y) for x, y in p['pts']]))
    return out

R = lambda v: round(v, 4)
def rp(pt): return [R(pt[0]), R(pt[1])]
def poly_coords(pg):
    return [rp(c) for c in list(pg.exterior.coords)[:-1]]

# ---------------------------------------------------------------- fixed parts
STAIR = (0.80, 4.80, 7.05, 9.80)                     # enclosure (outer face of walls)
LIFT_A = dict(name='Lift bank A (north)', outer=(47.95, 22.80, 55.65, 25.60),
              cars=[(48.15, 23.00, 50.45, 25.40), (50.65, 23.00, 52.95, 25.40), (53.15, 23.00, 55.45, 25.40)],
              door_side='S')
LIFT_B = dict(name='Lift bank B (east)', outer=(64.30, 0.30, 67.10, 8.35),
              cars=[(64.50, 0.75, 66.90, 3.15), (64.50, 3.35, 66.90, 5.65), (64.50, 5.85, 66.90, 8.15)],
              door_side='E')
LIFT_TOP = 28.5        # 1.5 m overrun above the main roof
VOID_C = [(12.25, 10.45), (24.05, 10.45), (21.95, 12.55), (21.95, 15.85), (12.25, 15.85)]
VOID_R_UPPER = [(68.90, 14.95), (73.85, 14.95), (73.85, 5.25), (69.85, 5.25), (69.85, 6.95)]
VOID_R_PARK = [(68.95, 14.95), (73.85, 14.95), (73.85, 6.95), (69.85, 6.95)]
ATRIUM = (64.0, -8.0, 74.0, 0.0)
PLOT = (-3.05, -12.05, 76.95, 37.95)                  # 80 m x 50 m (1 acre) plot boundary

EXCL = [(0.75, 4.75, 7.10, 9.85), (47.90, 22.75, 55.70, 25.65), (64.25, 0.25, 67.15, 8.40),
        (12.20, 10.40, 24.10, 15.90)]

def fully_inside(w, r):
    return all(r[0] <= p[0] <= r[2] and r[1] <= p[1] <= r[3] for p in (w['p0'], w['p1']))

def clip_out(w, r):
    """Remove the part of wall centreline inside rectangle r. Returns list of walls."""
    ls = LineString([w['p0'], w['p1']])
    rest = ls.difference(box(*r))
    parts = [rest] if rest.geom_type == 'LineString' else list(getattr(rest, 'geoms', []))
    out = []
    for prt in parts:
        if prt.length >= 0.35:
            c = list(prt.coords)
            out.append(dict(w, p0=c[0], p1=c[-1]))
    return out

def plan_walls(plan, layers):
    prims = plan_prims(plan, layers)
    W = merge(segs_from_prims(prims))
    W = [w for w in W if not any(fully_inside(w, r) for r in EXCL)]
    W2 = []
    for w in W:
        W2.extend(clip_out(w, STAIR))
    return W2

model = {
    'project': 'Entertainment Complex - Dewata, Galle (A2 road frontage)',
    'source': 'Concept_Desg2 (1).dwg + CAD explanation for 3d model.docx',
    'units': 'metres',
    'origin': 'Grid A1 of GROUND LEVEL PARKING PLAN = DWG (56.30, 28.12). +X east along frontage, +Y north.',
    'plan_offsets': {k: v['off'] for k, v in PLANS.items()},
    'levels': LEVELS,
    'assumptions': [],
    'walls': [], 'arc_walls': [], 'columns': [], 'slabs': [], 'surfaces': [], 'stairs': [],
    'lift_banks': [], 'escalators': [], 'ramps': [], 'parking_bays': [], 'seats': [],
    'risers': [], 'screens': [], 'spaces': [], 'doors': [], 'railings': [],
}
A = model['assumptions'].append

def add_wall(level, p0, p1, thk, h, kind, name, base=0.0, src=None):
    if math.hypot(p1[0] - p0[0], p1[1] - p0[1]) < 0.3:
        return
    model['walls'].append(dict(level=level, p0=rp(p0), p1=rp(p1), thk=thk, h=R(h), base=R(base), kind=kind, name=name, src=src))

# ---------------------------------------------------------------- walls per level
plan_levels = collections.defaultdict(list)
for l in LEVELS:
    if l['plan']:
        plan_levels[l['plan']].append(l)

def is_atrium_seg(w):
    return all(63.8 <= p[0] <= 74.2 and p[1] <= 0.15 for p in (w['p0'], w['p1'])) and not (
        abs(w['p0'][1]) < 0.15 and abs(w['p1'][1]) < 0.15)

def split_at_y0(w):
    """Split vertical walls that cross y=0 at x in atrium range."""
    (x0, y0), (x1, y1) = w['p0'], w['p1']
    if abs(x1 - x0) < 0.05 and 63.8 <= x0 <= 74.2 and min(y0, y1) < -0.1 < 0.1 < max(y0, y1):
        lo, hi = (w['p0'], w['p1']) if y0 < y1 else (w['p1'], w['p0'])
        return [dict(w, p0=lo, p1=(lo[0], 0.0)), dict(w, p0=(lo[0], 0.0), p1=hi)]
    return [w]

def split_front_x(w, xs):
    (x0, y0), (x1, y1) = w['p0'], w['p1']
    if abs(y1 - y0) > 0.05 or abs(y0) > 0.15:
        return [w]
    lo, hi = sorted([x0, x1])
    cuts = [lo] + [c for c in xs if lo + 0.05 < c < hi - 0.05] + [hi]
    return [dict(w, p0=(cuts[i], y0), p1=(cuts[i + 1], y0)) for i in range(len(cuts) - 1)]

STRAY = []
for plan in ['GF', 'P12', 'FF', 'TF']:
    masonry = plan_walls(plan, {'Exterior'})
    glazed = plan_walls(plan, {'Interior Boundaries'}) if plan in ('FF', 'TF') else []
    # glazed partitions that duplicate masonry walls are dropped
    mas_lines = [LineString([w['p0'], w['p1']]).buffer(0.12) for w in masonry]
    mas_union = unary_union(mas_lines) if mas_lines else None
    g2 = []
    for w in glazed:
        ls = LineString([w['p0'], w['p1']])
        rest = ls.difference(mas_union) if mas_union is not None else ls
        for prt in ([rest] if rest.geom_type == 'LineString' else list(getattr(rest, 'geoms', []))):
            if prt.length >= 0.5:
                c = list(prt.coords); g2.append(dict(w, p0=c[0], p1=c[-1]))
    glazed = g2
    # stray leftover line inside theatre T1 (copied from the first-floor plan) - would cut through seats
    if plan == 'TF':
        keep = []
        for w in masonry:
            if abs(w['p0'][0] - 23.95) < 0.1 and abs(w['p1'][0] - 23.95) < 0.1 and w['n_lines'] == 1:
                STRAY.append(w); continue
            keep.append(w)
        masonry = keep
    for lvl in plan_levels[plan]:
        lid, h = lvl['id'], lvl['height']
        for w in masonry:
            for w1 in split_at_y0(w):
                for w2 in (split_front_x(w1, [48.0, 64.0]) if lid in ('L03', 'L04') else split_front_x(w1, [64.0])):
                    p0, p1 = w2['p0'], w2['p1']
                    midx = (p0[0] + p1[0]) / 2; midy = (p0[1] + p1[1]) / 2
                    on_front = abs(p0[1]) < 0.15 and abs(p1[1]) < 0.15
                    if is_atrium_seg(w2):
                        top = ATRIUM_TOP - lvl['elev']
                        if top <= 0: continue
                        add_wall(lid, p0, p1, CW_T, min(h, top), 'curtain', 'Atrium glazing', src=plan)
                    elif on_front and 64.0 - 0.05 <= midx <= 74.0 and lid != 'L00':
                        model['railings'].append(dict(level=lid, p0=rp(p0), p1=rp(p1), h=PARAPET_H, kind='glass', name='Glass balustrade at atrium void'))
                    elif on_front and lid in ('L03', 'L04') and midx < 48.0:
                        add_wall(lid, p0, p1, CW_T, h, 'curtain', 'Front facade glazing', src=plan)
                    elif plan == 'P12' and midy < -0.1 and midx < 64.0:
                        add_wall(lid, p0, p1, WALL_T, PARAPET_H, 'parapet', 'Front planter / projection parapet', src=plan)
                    else:
                        add_wall(lid, p0, p1, WALL_T, h, 'masonry', 'Wall 200', src=plan)
        for w in glazed:
            add_wall(lid, w['p0'], w['p1'], GLAZ_T, h, 'glazed', 'Glazed partition (shopfront / foyer)', src=plan)
A('Walls are drawn in the DWG as double lines 100 mm apart; they are modelled on the drawn centre-line as 200 mm blockwork '
  '(glazed shopfront/foyer lines as 100 mm glazing). Curtain walls: the atrium box (x 64-74 m, in front of the frontage, up to +22.0 m '
  'per the front elevation) and the first/second-floor front facade (x 0-48 m, hatched glazing band in the front elevation).')
A('A stray single line at x = 24 m inside theatre 1 (left over from the first-floor plan) is ignored because it would cut through the seat rows.')

# curved corner wall (P12, FF, TF) and lobby box
for plan in ['FF', 'TF']:   # on the parking plan the same arc is only an overhead line (Interior Boundaries)
    arcs = [p for p in plan_prims(plan, {'Exterior'}, kinds=('arc',))
            if abs(p['radius'] - 4.0) < 0.01 and math.hypot(*[a - b for a, b in zip(g(plan, *p['center']), (3.95, 3.95))]) < 0.2]
    if not arcs:
        continue
    a = arcs[0]
    c = g(plan, *a['center'])
    for lvl in plan_levels[plan]:
        model['arc_walls'].append(dict(level=lvl['id'], center=rp(c), r=4.0, a0=180.0, a1=270.0, thk=GLAZ_T,
                                       h=lvl['height'], kind='glazed', name='Curved glazed entrance wall'))

# ---------------------------------------------------------------- utilities (ground floor)
def add_space(level, name, pts, h):
    model['spaces'].append(dict(level=level, name=name, poly=[rp(p) for p in pts], h=R(h)))
add_space('L00', 'Main Switch room', [(0.3, 0.3), (7.55, 0.3), (7.55, 4.3), (0.3, 4.3)], 3.2)
add_space('L00', 'CHILLER plant', [(63.95, 18.05), (73.95, 18.05), (73.95, 23.05), (63.95, 23.05)], 3.2)
add_space('L00', 'STP (sewage treatment plant)', [(64.95, 23.55), (73.95, 23.55), (73.95, 27.8), (64.95, 27.8)], 3.2)
for p0, p1 in [((0.3, 4.3), (7.55, 4.3)), ((7.55, 0.3), (7.55, 2.9)), ((7.55, 3.9), (7.55, 4.3)),
               ((63.95, 23.05), (73.95, 23.05)), ((64.95, 23.55), (73.95, 23.55)), ((64.95, 23.55), (64.95, 26.6)),
               ((64.95, 27.8), (73.95, 27.8))]:
    add_wall('L00', p0, p1, 0.15, 3.2, 'masonry', 'Service room partition 150', src='GF')
model['doors'].append(dict(level='L00', name='Main Switch room door', p=[7.55, 3.4], w=1.0, h=2.1, axis='y', leaves=1))
model['doors'].append(dict(level='L00', name='STP door', p=[64.95, 27.2], w=1.0, h=2.1, axis='y', leaves=1))

# ---------------------------------------------------------------- columns
def column_centres(plan):
    pts = set()
    for p in P:
        if p['kind'] != 'poly' or p['layer'] != 'Columns':
            continue
        xs = [q[0] for q in p['pts']]; ys = [q[1] for q in p['pts']]
        if abs(max(xs) - min(xs) - 0.6) < 0.06 and abs(max(ys) - min(ys) - 0.6) < 0.06:
            cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
            bb = PLANS[plan]['bbox']
            if bb[0] <= cx <= bb[2] and bb[1] <= cy <= bb[3]:
                gx, gy = g(plan, cx, cy)
                pts.add((round(gx * 20) / 20, round(gy * 20) / 20))
    return sorted(pts)

for plan in ['GF', 'P12', 'FF', 'TF']:
    cols = column_centres(plan)
    for lvl in plan_levels[plan]:
        for x, y in cols:
            model['columns'].append(dict(level=lvl['id'], x=R(x), y=R(y), w=0.6, d=0.6, h=lvl['height']))
A('Columns: 600 x 600 mm RC, taken from the "Columns" layer squares of each plan, full storey height.')

# ---------------------------------------------------------------- ramp (J-shaped helical ramp segment)
RC = (54.50, 23.75); R_IN, R_OUT, R_CL = 3.0, 9.0, 6.0
X_END = 47.70; Y_START = 14.00
L_STRAIGHT1 = RC[1] - Y_START          # north-bound leg
L_ARC = math.pi / 2 * R_CL
L_STRAIGHT2 = RC[0] - X_END            # west-bound leg
L_CL = L_STRAIGHT1 + L_ARC + L_STRAIGHT2

def ramp_polygon(n=24):
    inner, outer = [], []
    inner.append((RC[0] + R_IN, Y_START)); outer.append((RC[0] + 8.87, Y_START))
    for i in range(n + 1):
        a = math.pi / 2 * i / n
        inner.append((RC[0] + R_IN * math.cos(a), RC[1] + R_IN * math.sin(a)))
        outer.append((RC[0] + 8.87 * math.cos(a), RC[1] + R_OUT * math.sin(a)))
    inner.append((X_END, RC[1] + R_IN)); outer.append((X_END, RC[1] + R_OUT))
    return Polygon(inner + outer[::-1])

RAMP_PG = ramp_polygon()
for lo, hi in [('L00', 'L01'), ('L01', 'L02')]:
    z0, z1 = LV[lo]['elev'], LV[hi]['elev']
    model['ramps'].append(dict(
        name='Car ramp %s to %s' % (LV[lo]['name'], LV[hi]['name']), from_level=lo, to_level=hi,
        z0=z0, z1=z1, center=rp(RC), r_in=R_IN, r_out=R_OUT, r_out_x=8.87, r_cl=R_CL,
        x_end=X_END, y_start=Y_START, centerline_length=R(L_CL), slope_pct=R(100 * (z1 - z0) / L_CL),
        lanes=2, lane_width=3.0, thk=SLAB_T, kerb_h=1.0,
        start_up=rp((RC[0] + R_CL, Y_START)), end_down=rp((X_END, RC[1] + R_CL)),
        footprint=poly_coords(RAMP_PG)))
A('Ramp: the yellow "ramp" layer is the east turn of the parking loop - a 6.0 m wide, two-lane (2 x 3.0 m) J-shaped ramp, '
  'inner radius 3.0 m, outer radius 9.0 m, centre-line 25.97 m (as labelled). It starts at the "UP" end (x 57.5-63.4, y 14.0), '
  'runs north, turns 90 degrees anticlockwise and ends at the "DOWN" end (x 47.7, y 26.75-32.75), rising one storey (3.2 m): '
  'slope 3.2/25.97 = 12.3 % (1:8.1), within the usual 1:8 car-park ramp limit. The same ramp is stacked GF->P1 and P1->P2 so '
  'that, together with the flat loop aisle on each deck, cars drive a continuous spiral up/down the parking levels. 1.0 m '
  'kerb walls run along both ramp edges; the P1 and P2 slabs are opened over the ramp footprint.')

# ramp-opening edge upstands on the parking decks (P1: open at both ramp ends, P2: open only at the arrival end)
def ramp_edge_paths(off=0.12, n=12):
    inner = [(RC[0] + R_IN - off, Y_START - off), (RC[0] + R_IN - off, RC[1])]
    for i in range(1, n + 1):
        a = math.pi / 2 * i / n
        inner.append((RC[0] + (R_IN - off) * math.cos(a), RC[1] + (R_IN - off) * math.sin(a)))
    inner.append((X_END, RC[1] + R_IN - off))
    outer = [(RC[0] + 8.87 + off, Y_START - off), (RC[0] + 8.87 + off, RC[1])]
    for i in range(1, n + 1):
        a = math.pi / 2 * i / n
        outer.append((RC[0] + (8.87 + off) * math.cos(a), RC[1] + (R_OUT + off) * math.sin(a)))
    outer.append((X_END, RC[1] + R_OUT + off))
    bottom = [(RC[0] + R_IN - off, Y_START - off), (RC[0] + 8.87 + off, Y_START - off)]
    return inner, outer, bottom
_inner, _outer, _bottom = ramp_edge_paths()
for lid, paths in [('L01', [_inner, _outer]), ('L02', [_inner, _outer, _bottom])]:
    for path in paths:
        for i in range(len(path) - 1):
            add_wall(lid, path[i], path[i + 1], WALL_T, PARAPET_H, 'parapet', 'Ramp opening edge upstand 1.1 m', src='derived')
A('Edge protection: 1.1 m upstands line the ramp opening in the first and second parking decks (the second deck is closed at '
  'the lower ramp end, where its bottom lane would otherwise run into the opening).')

# ---------------------------------------------------------------- circulation loop and driveways (surface markings)
def annulus_q(c, r0, r1, a0, a1, n=24, r1x=None):
    r1x = r1x or r1
    pts = [(c[0] + r0 * math.cos(math.radians(a0 + (a1 - a0) * i / n)), c[1] + r0 * math.sin(math.radians(a0 + (a1 - a0) * i / n))) for i in range(n + 1)]
    pts += [(c[0] + r1x * math.cos(math.radians(a1 - (a1 - a0) * i / n)), c[1] + r1 * math.sin(math.radians(a1 - (a1 - a0) * i / n))) for i in range(n + 1)]
    return Polygon(pts)

LOOP = unary_union([
    box(17.3, 26.75, 47.7, 32.75),                         # north (top) lane, flat
    annulus_q((17.3, 23.75), 3.0, 9.0, 90, 180),           # NW turn
    box(8.3, 17.0, 14.3, 23.75),                           # west lane
    annulus_q((17.3, 17.0), 3.0, 9.0, 180, 270, r1x=9.0),  # SW turn
    box(17.3, 8.0, 63.37, 14.0),                           # south (bottom) lane up to the ramp start
]).buffer(0.001).buffer(-0.001)
ENTRY = unary_union([
    box(41.45, -7.05, 47.45, 8.0),                          # two-way entrance spine (6.0 m)
    box(17.45, -7.05, 41.45, -3.05), annulus_q((17.45, -9.05), 2.0, 6.0, 90, 180), box(11.45, -12.05, 15.45, -9.05),
    box(47.45, -7.05, 53.95, -3.05), annulus_q((53.95, -7.05), 0.001, 4.0, 0, 90), box(53.95, -12.05, 57.95, -7.05),
]).buffer(0.001).buffer(-0.001)
for lid in ['L00', 'L01', 'L02']:
    model['surfaces'].append(dict(level=lid, name='Vehicle circulation loop (drive aisle)', kind='drive', poly=poly_coords(LOOP), thk=0.02))
model['surfaces'].append(dict(level='L00', name='Entrance driveway from A2 road', kind='drive', poly=poly_coords(ENTRY), thk=0.02))
A('Vehicle circulation: the green elongated loop (two 3.0 m lanes, curved west end, ramp at the east end) is modelled as a 20 mm '
  'drive-aisle surface on every parking deck; the ground floor also has the two-way entrance spine and the two curved driveways to the A2 road.')

# ---------------------------------------------------------------- parking bays
for b in [p for p in P if p['kind'] == 'insert' and p['block'] == '3car bay']:
    plan = 'GF' if b['pts'][0][0] < 140 else 'P12'
    M = b['M']
    for (x0, x1) in [(-3.7, -1.2), (-1.2, 1.2), (1.2, 3.7)]:
        loc = [(x0, -5.0), (x1, -5.0), (x1, 0.0), (x0, 0.0)]
        wpts = [g(plan, M[0] * x + M[1] * y + M[2], M[3] * x + M[4] * y + M[5]) for x, y in loc]
        for lvl in plan_levels[plan]:
            model['parking_bays'].append(dict(level=lvl['id'], poly=[rp(p) for p in wpts]))
cnt = collections.Counter(b['level'] for b in model['parking_bays'])
model['parking_count'] = dict(cnt)
A('Parking stalls are taken from the 22 (ground) and 18 (first/second) "3car bay" blocks: %d stalls on the ground level '
  '(the drawing note says 63 - the DWG geometry is kept as drawn), %d on each of the first and second parking levels.' % (cnt['L00'], cnt['L01']))

# ---------------------------------------------------------------- lifts
for bank in (LIFT_A, LIFT_B):
    model['lift_banks'].append(dict(bank, z0=0.0, z1=LIFT_TOP, wall_t=0.2, stops=[l['id'] for l in LEVELS if l['id'] != 'L06']))
A('Lifts: two banks of 3 lift cars (crossed rectangles; not columns) - bank A at the north side (x 47.95-55.65, y 22.8-25.6), '
  'bank B at the east side (x 64.3-67.1, y 0.3-8.35). Shafts are continuous from ground to +28.5 m (1.5 m overrun), 200 mm walls, '
  'car 2.3-2.4 m x 2.4 m, 1.1 m landing door to every floor.')

# ---------------------------------------------------------------- stairs (dog-leg, enclosure 6.25 x 5.0 m)
def stair(lo, hi, x_land, x_top, n_risers):
    z0, z1 = LV[lo]['elev'], LV[hi]['elev']
    h = z1 - z0; per = n_risers // 2; rh = h / n_risers
    run = x_top - x_land; tread = run / (per - 1)
    return dict(name='Staircase %s to %s' % (LV[lo]['name'], LV[hi]['name']), from_level=lo, to_level=hi, z0=z0, z1=z1,
                riser=R(rh), tread=R(tread), risers=n_risers,
                flights=[dict(x_low=x_top, x_high=x_land, y0=4.90, y1=6.60, z0=z0, z1=z0 + h / 2, risers=per),
                         dict(x_low=x_land, x_high=x_top, y0=8.00, y1=9.70, z0=z0 + h / 2, z1=z1, risers=per)],
                landing=dict(x0=0.90, x1=x_land, y0=4.90, y1=9.70, z=z0 + h / 2, thk=0.2),
                spine=dict(x0=x_land, x1=6.95, y0=6.60, y1=8.00))
for lo, hi in [('L00', 'L01'), ('L01', 'L02'), ('L02', 'L03')]:
    model['stairs'].append(stair(lo, hi, 2.91, 5.15, 18))
for lo, hi in [('L03', 'L04'), ('L04', 'L05')]:
    model['stairs'].append(stair(lo, hi, 2.65, 5.73, 24))
A('Staircase: dog-leg stair in the 6.25 x 5.0 m enclosure at the west end (same position on every floor), two 1.7 m flights '
  'either side of a 1.4 m central spine wall, half landing on the west side, 1.8 m double doors to each floor. 3.2 m storeys: '
  '18 risers of 178 mm, 280 mm goings (as drawn: 8 treads per flight); 4.2 m storeys: 24 risers of 175 mm, 280 mm goings '
  '(11 treads per flight, as drawn). The stair serves ground to third floor.')

# stair enclosure walls (continuous) and doors per level
SX0, SY0, SX1, SY1 = STAIR
for lvl in LEVELS[:-1]:
    lid, h = lvl['id'], lvl['height']
    add_wall(lid, (SX0 + 0.1, SY0 + 0.1), (SX1 - 0.1, SY0 + 0.1), 0.2, h, 'masonry', 'Stair enclosure wall')
    add_wall(lid, (SX0 + 0.1, SY1 - 0.1), (SX1 - 0.1, SY1 - 0.1), 0.2, h, 'masonry', 'Stair enclosure wall')
    add_wall(lid, (SX0 + 0.1, SY0), (SX0 + 0.1, SY1), 0.2, h, 'masonry', 'Stair enclosure wall')
    add_wall(lid, (SX1 - 0.1, 6.60), (SX1 - 0.1, 8.00), 0.2, h, 'masonry', 'Stair enclosure wall')
    for y0, y1 in [(4.90, 6.60), (8.00, 9.70)]:
        add_wall(lid, (SX1 - 0.1, y0), (SX1 - 0.1, y1), 0.2, h - 2.1, 'masonry', 'Lintel over stair door', base=2.1)
        model['doors'].append(dict(level=lid, name='Stair door (double, 1.8 m)', p=[SX1 - 0.1, (y0 + y1) / 2], w=y1 - y0, h=2.1, axis='y', leaves=2))
    if lid != 'L05':
        x_land = 2.91 if lid in ('L00', 'L01', 'L02') else 2.65
        add_wall(lid, (x_land, 7.30), (SX1 - 0.2, 7.30), 1.4, h, 'masonry', 'Stair central spine wall')

# ---------------------------------------------------------------- escalators
def esc(name, lo, hi, axis, a0, a1, b0, b1, bottom_end):
    """axis: direction of travel ('x' or 'y'); a0..a1 along axis, b0..b1 across; bottom_end: 'min' or 'max'."""
    z0, z1 = LV[lo]['elev'], LV[hi]['elev']
    w = (b1 - b0) / 2
    out = []
    for i, tag in enumerate(['up', 'down']):
        out.append(dict(name='%s %s (%s)' % (name, i + 1, tag), from_level=lo, to_level=hi, axis=axis, a0=R(a0), a1=R(a1),
                        b0=R(b0 + i * w), b1=R(b0 + (i + 1) * w), bottom_end=bottom_end, z0=z0, z1=z1, angle=30.0))
    return out
for lo, hi in [('L00', 'L01'), ('L01', 'L02'), ('L02', 'L03')]:
    model['escalators'] += esc('Escalator 8 m (east)', lo, hi, 'y', 6.95, 14.95, 69.85, 72.75, 'max')
for lo, hi in [('L03', 'L04'), ('L04', 'L05')]:
    model['escalators'] += esc('Escalator 9.7 m (east)', lo, hi, 'y', 5.25, 14.95, 69.85, 72.75, 'max')
    model['escalators'] += esc('Escalator 9.6 m (central)', lo, hi, 'x', 12.37, 21.95, 12.85, 15.15, 'max')
A('Escalators: pairs (one up, one down) at 30 degrees. East pair: 8 m units ground->P1->P2->first floor and 9.7 m units '
  'first->second->third floor (lower end at the north/"UP" end). Central pair: 9.6 m units first->second->third floor '
  '(lower end at the east/"UP" end). Slab voids as drawn on the "void" layer, with 1.1 m glass balustrades.')

# ---------------------------------------------------------------- slabs
def hole_pg(pts): return Polygon(pts)
def rect(x0, y0, x1, y1): return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
lift_holes = [rect(*LIFT_A['outer']), rect(*LIFT_B['outer'])]
PARK_OUT = Polygon([(0, 0), (74, 0), (74, 18), (64, 18), (64, 34), (0, 34)])
UP_OUT = Polygon([(0, 0), (74, 0), (74, 18), (64, 18), (64, 26), (0, 26)])

def add_slab(level, name, outer_pg, holes=(), thk=SLAB_T, top=None, kind='floor'):
    pg = outer_pg
    for h in holes:
        pg = pg.difference(Polygon(h) if not isinstance(h, Polygon) else h)
    geoms = [pg] if pg.geom_type == 'Polygon' else list(pg.geoms)
    for gg in geoms:
        if gg.area < 0.5: continue
        gg = gg.simplify(0.005)
        model['slabs'].append(dict(level=level, name=name, kind=kind, outer=poly_coords(gg),
                                   holes=[[rp(c) for c in list(r.coords)[:-1]] for r in gg.interiors],
                                   thk=thk, top=R(LV[level]['elev'] if top is None else top)))

add_slab('L00', 'Ground slab and external paving (plot 80 x 50 m)', box(*PLOT), thk=0.25)
for lid, stair_x in [('L01', 5.15), ('L02', 5.15)]:
    add_slab(lid, 'Parking deck slab', PARK_OUT, [RAMP_PG, rect(SX0, SY0, stair_x, SY1), VOID_R_PARK] + lift_holes)
add_slab('L01', 'Plant room roof (STP / chiller)', box(64, 18.05, 74, 28.3))
add_slab('L03', 'Floor slab', UP_OUT, [rect(SX0, SY0, 5.15, SY1), VOID_R_UPPER] + lift_holes)
add_slab('L03', 'Podium roof over second parking level (rear)', box(0, 26, 64, 34), kind='roof')
for lid in ['L04', 'L05']:
    add_slab(lid, 'Floor slab', UP_OUT, [rect(SX0, SY0, 5.73, SY1), VOID_R_UPPER, VOID_C] + lift_holes)
add_slab('L06', 'Main roof slab', UP_OUT, lift_holes, kind='roof')
model['slabs'].append(dict(level='L05', name='Atrium roof (+22.0)', kind='roof', outer=[rp(p) for p in rect(64, -8, 74, 0)], holes=[], thk=SLAB_T, top=ATRIUM_TOP))
for b in (LIFT_A, LIFT_B):
    model['slabs'].append(dict(level='L06', name='Lift shaft cap (+28.5)', kind='roof', outer=[rp(p) for p in rect(*b['outer'])], holes=[], thk=0.2, top=LIFT_TOP))
A('Slabs: 200 mm RC (250 mm ground slab extended over the 80 x 50 m plot as external paving). The parking decks are 74 x 34 m '
  '(with the east wing), the upper floors 74 x 26 m (as drawn). The rear strip of the second parking deck (y 26-34 m) is '
  'covered by a podium roof slab at first-floor level, the single-storey STP/chiller annex has its own roof, the glazed '
  'atrium box (x 64-74, y -8-0) is open from ground to its roof at +22.0 m.')

# podium roof parapet
for p0, p1 in [((0, 34), (64, 34)), ((0, 26), (0, 34)), ((64, 26), (64, 34))]:
    add_wall('L03', p0, p1, WALL_T, PARAPET_H, 'parapet', 'Podium roof parapet')
# front planter/projection slab on P1 / P2 (trapezoid drawn on the parking plan)
for lid in ['L01', 'L02']:
    model['slabs'].append(dict(level=lid, name='Front planter / projection slab', kind='floor',
                               outer=[[0, 0], [32, -5.5], [56, -5.5], [64, 0]], holes=[], thk=0.2, top=LV[lid]['elev']))
A('The trapezoidal outline in front of the first/second parking plan (projecting 5.5 m, divided at x = 32/40/48/56 m) is '
  'modelled as a projecting planter slab with 1.1 m parapets on both parking decks.')

# balustrades around voids
def ring(pts, level, name, skip_edges=()):
    n = len(pts)
    for i in range(n):
        if i in skip_edges: continue
        model['railings'].append(dict(level=level, p0=rp(pts[i]), p1=rp(pts[(i + 1) % n]), h=PARAPET_H, kind='glass', name=name))
for lid in ['L04', 'L05']:
    ring(VOID_C, lid, 'Glass balustrade - central escalator void', skip_edges=(1,))
for lid in ['L01', 'L02']:
    ring(VOID_R_PARK, lid, 'Glass balustrade - east escalator void', skip_edges=(1, 2))
for lid in ['L03', 'L04', 'L05']:
    ring(VOID_R_UPPER, lid, 'Glass balustrade - east escalator void', skip_edges=(1, 2, 3))

# ---------------------------------------------------------------- cinema: theatres, screens, risers, seats
TH = {
    'T1': dict(name='Theatre 1 (108 seats)', poly=[(8.0, 17.83), (26.92, 17.83), (26.92, 25.9), (8.0, 25.9)], face='-x'),
    'T2': dict(name='Theatre 2 (200 seats)', poly=[(26.92, 14.0), (43.92, 14.0), (48.0, 18.05), (48.0, 25.9), (26.92, 25.9)], face='-x'),
    'T3': dict(name='Theatre 3 (136 seats)', poly=[(48.0, 0.0), (63.87, 0.0), (63.87, 13.83), (51.32, 13.83), (48.0, 10.5)], face='-y'),
}
def which_theatre(x, y):
    for k, t in TH.items():
        if Polygon(t['poly']).buffer(0.05).contains(Point(x, y)): return k
seats = []
for s in [p for p in P if p['kind'] == 'insert' and p['block'] == 'seat']:
    M = s['M']
    x, y = g('TF', M[2], M[5])
    rot = math.degrees(math.atan2(M[3], M[0]))
    k = which_theatre(x, y)
    seats.append(dict(t=k, x=x, y=y, rot=rot))
L5 = LV['L05']['elev']
for k, t in TH.items():
    S = [s for s in seats if s['t'] == k]
    key = (lambda s: s['x']) if t['face'] == '-x' else (lambda s: s['y'])
    rows = sorted(set(round(key(s), 1) for s in S))
    t['rows'] = len(rows); t['seats'] = len(S)
    tp = Polygon(t['poly']).buffer(-0.10)
    for i, rv in enumerate(rows):
        z_top = i * RISER_H
        if i == 0: continue
        front = rv - 0.725 - 0.35
        back = (rows[i + 1] - 0.725 - 0.35) if i + 1 < len(rows) else 99.0
        if t['face'] == '-x':
            strip = box(front, -99, back, 99)
        else:
            strip = box(-99, front, 99, back)
        pg = tp.intersection(strip)
        if pg.is_empty: continue
        for gg in ([pg] if pg.geom_type == 'Polygon' else list(pg.geoms)):
            model['risers'].append(dict(level='L05', theatre=k, row=i + 1, poly=poly_coords(gg.simplify(0.005)), z0=L5, z1=R(L5 + z_top)))
    for s in S:
        i = rows.index(round(key(s), 1))
        model['seats'].append(dict(level='L05', theatre=k, row=i + 1, x=R(s['x']), y=R(s['y']), rot=R(s['rot']), z=R(L5 + i * RISER_H)))
    model['spaces'].append(dict(level='L05', name=t['name'], poly=[rp(p) for p in t['poly']], h=9.0))
SCR = [('T1', 'Screen - Theatre 1', g('TF', 170.80, 127.72), 9.25, 161.1, 198.9, 3.2),
       ('T2', 'Screen - Theatre 2', g('TF', 200.71, 125.42), 20.31, 167.9, 192.1, 4.2),
       ('T3', 'Screen - Theatre 3', g('TF', 208.25, 126.74), 20.31, 257.9, 282.1, 4.2)]
for k, name, c, r, a0, a1, hh in SCR:
    model['screens'].append(dict(level='L05', theatre=k, name=name, center=rp(c), r=r, a0=a0, a1=a1, z0=R(L5 + 1.2), h=hh, thk=0.08))
model['theatres'] = {k: dict(name=t['name'], rows=t['rows'], seats=t['seats'], faces=t['face']) for k, t in TH.items()}
A('Cinema (third floor, 9.0 m storey): theatre 1 (upper-left, 12 rows x 9 = 108 seats) and theatre 2 (upper-middle, 13 rows, '
  '200 seats) face curved screens on their WEST walls; theatre 3 (lower-right, 7 rows, 136 seats) faces a curved screen on its '
  'SOUTH wall - all taken from the magenta seat blocks and screen arcs in the DWG. Stadium seating rises 350 mm per row '
  '(back rows of T1/T2 at +3.85/+4.2 m, leaving > 4.5 m headroom). Screens: 6.0 m (T1) and 8.5 m (T2, T3) wide, '
  'bottom edge 1.2 m above the floor.')

# ---------------------------------------------------------------- summary
model['summary'] = {k: len(v) for k, v in model.items() if isinstance(v, list)}
model['stray_lines_ignored'] = [dict(p0=rp(w['p0']), p1=rp(w['p1'])) for w in STRAY]
json.dump(model, open(OUT, 'w'), indent=1)
print(json.dumps(model['summary']))
print(model['parking_count'], model['theatres'])
