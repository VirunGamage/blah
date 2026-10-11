# -*- coding: utf-8 -*-
"""
Entertainment Complex (Dewata, Galle) - native Revit model builder.

Reads model.json (extracted from "Concept_Desg2 (1).dwg" following
"CAD explanation for 3d model.docx") and builds the building in the ACTIVE
Revit document, then saves it as Entertainment_Complex.rvt and exports
Entertainment_Complex.dwf / .dwfx next to model.json.

How to run (Revit 2027; any Revit 2023+ should work):
  * Dynamo (built into Revit): Manage > Dynamo > New. Add a "File Path" node
    pointing at model.json and connect it to IN[0] of a "Python Script" node
    (engine CPython3 / PythonNet3). Paste this whole file into that node and
    press Run.
  * pyRevit / RevitPythonShell: run this file directly. model.json must be in
    the same folder (otherwise a file dialog asks for it).

Start from a NEW project (File > New > Project > Architectural/Metric
template). The script adds levels, grids, walls, floors, columns, stairs,
ramps, lifts, escalators, parking stalls, cinema seating and screens.
Elements that have no reliable native API (helical ramp, escalators,
seats, screens, stadium risers, lift cars) are DirectShapes in the proper
Revit category.  Warnings are suppressed; a log file is written.

Units: model.json is in metres; Revit internal units are feet.
"""
from __future__ import print_function
import clr, json, math, os, io, traceback

clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
clr.AddReference('System')
from System.Collections.Generic import List
from Autodesk.Revit.DB import *                      # noqa: F401,F403
from Autodesk.Revit.DB.Architecture import *         # noqa: F401,F403
from Autodesk.Revit.DB.Structure import StructuralType

# ------------------------------------------------------------------ host detection
DYNAMO = False
try:
    doc = __revit__.ActiveUIDocument.Document        # noqa: F821  (pyRevit / RevitPythonShell)
    app = __revit__.Application                      # noqa: F821
except NameError:
    clr.AddReference('RevitServices')
    from RevitServices.Persistence import DocumentManager
    from RevitServices.Transactions import TransactionManager
    doc = DocumentManager.Instance.CurrentDBDocument
    app = DocumentManager.Instance.CurrentUIApplication.Application
    TransactionManager.Instance.ForceCloseTransaction()
    DYNAMO = True


def find_model_json():
    cands = []
    try:
        cands.append(str(IN[0]))                     # noqa: F821  (Dynamo input)
    except Exception:
        pass
    try:
        cands.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'model.json'))
    except Exception:
        pass
    for c in cands:
        if c and os.path.isfile(c):
            return c
    clr.AddReference('System.Windows.Forms')
    from System.Windows.Forms import OpenFileDialog, DialogResult
    dlg = OpenFileDialog()
    dlg.Filter = 'model.json|*.json'
    dlg.Title = 'Select model.json (Entertainment Complex)'
    if dlg.ShowDialog() == DialogResult.OK:
        return dlg.FileName
    raise Exception('model.json not found')


MODEL_PATH = find_model_json()
OUT_DIR = os.path.dirname(MODEL_PATH)
with io.open(MODEL_PATH, 'r', encoding='utf-8') as fh:
    M = json.load(fh)

LOG = []
def log(msg):
    LOG.append(msg)
    try:
        print(msg)
    except Exception:
        pass

FT = 1.0 / 0.3048
def ft(v):
    return float(v) * FT
def P(x, y, z=0.0):
    return XYZ(ft(x), ft(y), ft(z))


# ------------------------------------------------------------------ failure handling
class SwallowWarnings(IFailuresPreprocessor):
    __namespace__ = 'EntertainmentComplexBuilder'

    def PreprocessFailures(self, fa):
        resolved = False
        try:
            for f in list(fa.GetFailureMessages()):
                sev = f.GetSeverity()
                if sev == FailureSeverity.Warning:
                    fa.DeleteWarning(f)
                elif sev == FailureSeverity.Error:
                    if f.HasResolutions():
                        fa.ResolveFailure(f)
                        resolved = True
                    else:
                        ids = List[ElementId](f.GetFailingElementIds())
                        if ids.Count > 0:
                            fa.DeleteElements(ids)
                            resolved = True
        except Exception:
            pass
        return FailureProcessingResult.ProceedWithCommit if resolved else FailureProcessingResult.Continue


class Tx(object):
    def __init__(self, name):
        self.t = Transaction(doc, name)

    def __enter__(self):
        self.t.Start()
        o = self.t.GetFailureHandlingOptions()
        o.SetFailuresPreprocessor(SwallowWarnings())
        o.SetClearAfterRollback(True)
        self.t.SetFailureHandlingOptions(o)
        return self.t

    def __exit__(self, et, ev, tb):
        if et is None:
            self.t.Commit()
        else:
            log('Transaction %s rolled back: %s' % (self.t.GetName(), ev))
            self.t.RollBack()
        return False


STATS = {}
ERRORS = {}
def ok(kind):
    STATS[kind] = STATS.get(kind, 0) + 1
def fail(kind, e):
    ERRORS[kind] = ERRORS.get(kind, 0) + 1
    if ERRORS[kind] <= 3:
        log('  ! %s failed: %s' % (kind, e))


def collect(cls):
    return list(FilteredElementCollector(doc).OfClass(cls))


def by_name(cls, name):
    for e in collect(cls):
        try:
            if e.Name == name:
                return e
        except Exception:
            pass
    return None


# ------------------------------------------------------------------ materials
MAT = {}
def material(name, rgb, transparency=0):
    m = by_name(Material, name)
    if m is None:
        m = doc.GetElement(Material.Create(doc, name))
    m.Color = Color(int(rgb[0]), int(rgb[1]), int(rgb[2]))
    m.Transparency = int(transparency)
    MAT[name] = m.Id
    return m.Id


# ------------------------------------------------------------------ types
def wall_type(name, width_m, mat_name):
    wt = by_name(WallType, name)
    if wt is None:
        base = [w for w in collect(WallType) if w.Kind == WallKind.Basic][0]
        wt = base.Duplicate(name)
    cs = CompoundStructure.CreateSingleLayerCompoundStructure(MaterialFunctionAssignment.Structure, ft(width_m), MAT[mat_name])
    wt.SetCompoundStructure(cs)
    return wt.Id


def curtain_type():
    cw = [w for w in collect(WallType) if w.Kind == WallKind.Curtain]
    for pref in ('Storefront', 'Curtain Wall 1', 'Curtain Wall - Storefront'):
        for w in cw:
            if w.Name == pref:
                return w.Id
    return cw[0].Id if cw else None


def floor_type(name, thk_m, mat_name):
    ftp = by_name(FloorType, name)
    if ftp is None:
        base = [f for f in collect(FloorType) if not f.IsFoundationSlab][0]
        ftp = base.Duplicate(name)
    cs = CompoundStructure.CreateSingleLayerCompoundStructure(MaterialFunctionAssignment.Structure, ft(thk_m), MAT[mat_name])
    ftp.SetCompoundStructure(cs)
    return ftp.Id


# ------------------------------------------------------------------ levels, views, grids
LEVEL = {}
PLAN_VIEWS = []
def build_levels():
    existing = collect(Level)
    for L in M['levels']:
        lv = None
        for e in existing:
            if abs(e.Elevation - ft(L['elev'])) < 0.01:
                lv = e
        if lv is None:
            lv = Level.Create(doc, ft(L['elev']))
        try:
            lv.Name = L['name']
        except Exception:
            lv.Name = L['name'] + ' (%s)' % L['id']
        LEVEL[L['id']] = lv
    vft = [v for v in collect(ViewFamilyType) if v.ViewFamily == ViewFamily.FloorPlan][0]
    have = set()
    for v in collect(ViewPlan):
        try:
            if not v.IsTemplate and v.GenLevel is not None and v.ViewType == ViewType.FloorPlan:
                have.add(v.GenLevel.Id.ToString())
        except Exception:
            pass
    for L in M['levels']:
        lv = LEVEL[L['id']]
        if lv.Id.ToString() in have:
            for v in collect(ViewPlan):
                try:
                    if not v.IsTemplate and v.GenLevel is not None and v.GenLevel.Id.ToString() == lv.Id.ToString() and v.ViewType == ViewType.FloorPlan:
                        PLAN_VIEWS.append(v)
                        break
                except Exception:
                    pass
            continue
        v = ViewPlan.Create(doc, vft.Id, lv.Id)
        try:
            v.Name = L['name']
        except Exception:
            pass
        PLAN_VIEWS.append(v)


def build_grids():
    gx = [0.0, 8.0, 16.0, 24.0, 32.0, 40.0, 48.0, 56.0, 64.0, 73.9]
    gy = [('A', -8.0), ('B', 0.0), ('C', 8.0), ('D', 18.0), ('E', 25.9), ('F', 33.9)]
    names = set(g.Name for g in collect(Grid))
    for i, x in enumerate(gx):
        try:
            g = Grid.Create(doc, Line.CreateBound(P(x, -13), P(x, 39)))
            n = str(i + 1)
            if n not in names:
                g.Name = n
            ok('grid')
        except Exception as e:
            fail('grid', e)
    for n, y in gy:
        try:
            g = Grid.Create(doc, Line.CreateBound(P(-5, y), P(79, y)))
            if n not in names:
                g.Name = n
            ok('grid')
        except Exception as e:
            fail('grid', e)


# ------------------------------------------------------------------ helpers
def set_param(el, bip, value):
    try:
        p = el.get_Parameter(bip)
        if p is not None and not p.IsReadOnly:
            p.Set(value)
            return True
    except Exception:
        pass
    return False


def comment(el, text):
    set_param(el, BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS, text)


def clean_pts(pts, tol=0.01):
    out = []
    for p in pts:
        if not out or math.hypot(p[0] - out[-1][0], p[1] - out[-1][1]) > tol:
            out.append(p)
    if len(out) > 2 and math.hypot(out[0][0] - out[-1][0], out[0][1] - out[-1][1]) <= tol:
        out.pop()
    return out


def area2(pts):
    return sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1] for i in range(len(pts))) / 2.0


def curve_loop(pts, z=0.0, ccw=True):
    pts = clean_pts(pts)
    if (area2(pts) > 0) != ccw:
        pts = pts[::-1]
    cl = CurveLoop()
    n = len(pts)
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        cl.Append(Line.CreateBound(P(a[0], a[1], z), P(b[0], b[1], z)))
    return cl


def loops(outer, holes=(), z=0.0):
    ls = List[CurveLoop]()
    ls.Add(curve_loop(outer, z, True))
    for h in holes:
        ls.Add(curve_loop(h, z, False))
    return ls


def ds_category(bic):
    cid = ElementId(bic)
    try:
        if DirectShape.IsValidCategoryId(cid, doc):
            return cid
    except Exception:
        pass
    return ElementId(BuiltInCategory.OST_GenericModel)


def direct_shape(bic, geoms, name, mat_name=None):
    ds = DirectShape.CreateElement(doc, ds_category(bic))
    gl = List[GeometryObject]()
    for g in geoms:
        gl.Add(g)
    ds.SetShape(gl)
    try:
        ds.Name = name
    except Exception:
        pass
    comment(ds, name)
    return ds


def opts_mat(mat_name):
    o = SolidOptions(MAT[mat_name], ElementId.InvalidElementId) if mat_name in MAT else SolidOptions(ElementId.InvalidElementId, ElementId.InvalidElementId)
    return o


def prism(pts, z0, h, mat_name=None):
    """Vertical extrusion of a plan polygon (metres)."""
    return GeometryCreationUtilities.CreateExtrusionGeometry(loops(pts, (), z0), XYZ.BasisZ, ft(h), opts_mat(mat_name))


def vprism(prof, origin, t, n, width, mat_name=None):
    """Extrude a profile drawn in the vertical plane (u along t, v up) by width along n."""
    prof = list(prof)
    if area2(prof) < 0:
        prof = prof[::-1]
    pts3 = []
    for u, v in prof:
        pts3.append(XYZ(ft(origin[0] + t[0] * u), ft(origin[1] + t[1] * u), ft(origin[2] + v)))
    cl = CurveLoop()
    k = len(pts3)
    for i in range(k):
        a, b = pts3[i], pts3[(i + 1) % k]
        if a.DistanceTo(b) > 0.003:
            cl.Append(Line.CreateBound(a, b))
    ls = List[CurveLoop]()
    ls.Add(cl)
    return GeometryCreationUtilities.CreateExtrusionGeometry(ls, XYZ(n[0], n[1], n[2]), ft(width), opts_mat(mat_name))


def mesh_solid(tris, mat_name=None):
    b = TessellatedShapeBuilder()
    b.OpenConnectedFaceSet(True)
    mid = MAT.get(mat_name, ElementId.InvalidElementId)
    for tri in tris:
        pl = List[XYZ]()
        for p in tri:
            pl.Add(P(p[0], p[1], p[2]))
        b.AddFace(TessellatedFace(pl, mid))
    b.CloseConnectedFaceSet()
    b.Target = TessellatedShapeBuilderTarget.AnyGeometry
    b.Fallback = TessellatedShapeBuilderFallback.Mesh
    b.Build()
    return list(b.GetBuildResult().GetGeometricalObjects())


def band_tris(secs):
    """secs: list of (a_xy, b_xy, z_bot, z_top) -> triangles of a closed swept band."""
    T = []
    def Q(i, side, top):
        a, b, zb, zt = secs[i]
        xy = a if side == 0 else b
        return (xy[0], xy[1], zt if top else zb)
    n = len(secs)
    for i in range(n - 1):
        T += [[Q(i, 0, 1), Q(i, 1, 1), Q(i + 1, 1, 1)], [Q(i, 0, 1), Q(i + 1, 1, 1), Q(i + 1, 0, 1)]]
        T += [[Q(i, 0, 0), Q(i + 1, 1, 0), Q(i, 1, 0)], [Q(i, 0, 0), Q(i + 1, 0, 0), Q(i + 1, 1, 0)]]
        T += [[Q(i, 0, 0), Q(i, 0, 1), Q(i + 1, 0, 1)], [Q(i, 0, 0), Q(i + 1, 0, 1), Q(i + 1, 0, 0)]]
        T += [[Q(i, 1, 0), Q(i + 1, 1, 0), Q(i + 1, 1, 1)], [Q(i, 1, 0), Q(i + 1, 1, 1), Q(i, 1, 1)]]
    T += [[Q(0, 0, 0), Q(0, 1, 0), Q(0, 1, 1)], [Q(0, 0, 0), Q(0, 1, 1), Q(0, 0, 1)]]
    T += [[Q(n - 1, 0, 0), Q(n - 1, 0, 1), Q(n - 1, 1, 1)], [Q(n - 1, 0, 0), Q(n - 1, 1, 1), Q(n - 1, 1, 0)]]
    return T


def lv_elev(lid):
    for L in M['levels']:
        if L['id'] == lid:
            return L['elev']


# ------------------------------------------------------------------ walls
WT = {}
def build_walls():
    cw = curtain_type()
    for w in M['walls']:
        try:
            a, b = w['p0'], w['p1']
            line = Line.CreateBound(P(a[0], a[1]), P(b[0], b[1]))
            kind = w['kind']
            if kind == 'curtain' and cw is not None:
                tid = cw
            elif kind in ('glazed', 'curtain'):
                tid = WT['glazed']
            elif kind == 'parapet':
                tid = WT['parapet']
            elif abs(w['thk'] - 1.4) < 0.01:
                tid = WT['spine']
            elif abs(w['thk'] - 0.15) < 0.01:
                tid = WT['partition']
            else:
                tid = WT['block']
            wall = Wall.Create(doc, line, tid, LEVEL[w['level']].Id, ft(w['h']), ft(w['base']), False, False)
            set_param(wall, BuiltInParameter.WALL_KEY_REF_PARAM, 0)        # location line = wall centreline
            comment(wall, w['name'])
            ok('wall')
        except Exception as e:
            fail('wall', e)
    for w in M['arc_walls']:
        try:
            c = P(w['center'][0], w['center'][1])
            arc = Arc.Create(c, ft(w['r']), math.radians(w['a0']), math.radians(w['a1']), XYZ.BasisX, XYZ.BasisY)
            wall = Wall.Create(doc, arc, WT['glazed'], LEVEL[w['level']].Id, ft(w['h']), 0.0, False, False)
            comment(wall, w['name'])
            ok('curved wall')
        except Exception as e:
            fail('curved wall', e)


def build_railings():
    rtypes = collect(RailingType)
    rt = None
    for r in rtypes:
        if 'Glass' in r.Name:
            rt = r
    if rt is None and rtypes:
        rt = rtypes[0]
    for r in M['railings']:
        done = False
        if rt is not None:
            try:
                cl = CurveLoop()
                cl.Append(Line.CreateBound(P(r['p0'][0], r['p0'][1]), P(r['p1'][0], r['p1'][1])))
                rl = Railing.Create(doc, cl, rt.Id, LEVEL[r['level']].Id)
                comment(rl, r['name'])
                done = True
                ok('railing')
            except Exception as e:
                fail('railing (native)', e)
        if not done:
            try:
                line = Line.CreateBound(P(r['p0'][0], r['p0'][1]), P(r['p1'][0], r['p1'][1]))
                wall = Wall.Create(doc, line, WT['balustrade'], LEVEL[r['level']].Id, ft(r['h']), 0.0, False, False)
                comment(wall, r['name'])
                ok('railing (glass wall)')
            except Exception as e:
                fail('railing', e)


# ------------------------------------------------------------------ floors / slabs
def make_floor(outer, holes, type_id, lid, top_m, name):
    fl = Floor.Create(doc, loops(outer, holes), type_id, LEVEL[lid].Id)
    set_param(fl, BuiltInParameter.FLOOR_HEIGHTABOVELEVEL_PARAM, ft(top_m - lv_elev(lid)))
    comment(fl, name)
    return fl


def build_slabs():
    for s in M['slabs']:
        try:
            if s['level'] == 'L00':
                tid = FTY['ground']
            elif s['kind'] == 'roof':
                tid = FTY['roof']
            else:
                tid = FTY['slab']
            make_floor(s['outer'], s['holes'], tid, s['level'], s['top'], s['name'])
            ok('floor/roof slab')
        except Exception as e:
            fail('floor/roof slab', e)
            try:
                direct_shape(BuiltInCategory.OST_Floors, [prism(s['outer'], s['top'] - s['thk'], s['thk'], 'Concrete')], s['name'])
                ok('floor (directshape fallback)')
            except Exception as e2:
                fail('floor fallback', e2)
    for s in M['surfaces']:
        try:
            make_floor(s['poly'], (), FTY['drive'], s['level'], lv_elev(s['level']) + s['thk'], s['name'])
            ok('drive aisle surface')
        except Exception as e:
            fail('drive aisle surface', e)
    for b in M['parking_bays']:
        try:
            pts = b['poly']
            cx = sum(p[0] for p in pts) / 4.0
            cy = sum(p[1] for p in pts) / 4.0
            ins = [(cx + (p[0] - cx) * 0.96, cy + (p[1] - cy) * 0.985) for p in pts]
            direct_shape(BuiltInCategory.OST_Parking, [prism(ins, lv_elev(b['level']), 0.025, 'Parking bay paint')], 'Parking stall')
            ok('parking stall')
        except Exception as e:
            fail('parking stall', e)


# ------------------------------------------------------------------ columns
def column_symbol():
    syms = [s for s in collect(FamilySymbol) if s.Category is not None and
            s.Category.Id.Equals(ElementId(BuiltInCategory.OST_StructuralColumns))]
    if not syms:
        paths = []
        try:
            for kv in app.GetLibraryPaths():
                paths.append(kv.Value)
        except Exception:
            pass
        paths.append(r'C:\ProgramData\Autodesk\RVT %s\Libraries' % app.VersionNumber)
        target = ('M_Concrete-Rectangular-Column.rfa', 'Concrete-Rectangular-Column.rfa')
        found = None
        for root in paths:
            if found or not os.path.isdir(root):
                continue
            for dp, dn, fn in os.walk(root):
                for f in fn:
                    if f in target:
                        found = os.path.join(dp, f)
                        break
                if found:
                    break
        if found:
            doc.LoadFamily(found)
            syms = [s for s in collect(FamilySymbol) if s.Category is not None and
                    s.Category.Id.Equals(ElementId(BuiltInCategory.OST_StructuralColumns))]
    if not syms:
        return None
    base = syms[0]
    sym = None
    for s in syms:
        if s.Name == '600 x 600mm (EC)':
            sym = s
    if sym is None:
        try:
            sym = base.Duplicate('600 x 600mm (EC)')
        except Exception:
            sym = base
    for pn in ('b', 'h', 'Width', 'Depth'):
        try:
            p = sym.LookupParameter(pn)
            if p is not None and not p.IsReadOnly:
                p.Set(ft(0.6))
        except Exception:
            pass
    if not sym.IsActive:
        sym.Activate()
    return sym


def build_columns():
    sym = column_symbol()
    ids = [L['id'] for L in M['levels']]
    for c in M['columns']:
        try:
            if sym is None:
                raise Exception('no structural column family loaded')
            lv = LEVEL[c['level']]
            top = LEVEL[ids[ids.index(c['level']) + 1]]
            inst = doc.Create.NewFamilyInstance(P(c['x'], c['y']), sym, lv, StructuralType.Column)
            set_param(inst, BuiltInParameter.FAMILY_BASE_LEVEL_PARAM, lv.Id)
            set_param(inst, BuiltInParameter.FAMILY_TOP_LEVEL_PARAM, top.Id)
            set_param(inst, BuiltInParameter.FAMILY_BASE_LEVEL_OFFSET_PARAM, 0.0)
            set_param(inst, BuiltInParameter.FAMILY_TOP_LEVEL_OFFSET_PARAM, ft(lv_elev(c['level']) + c['h'] - lv_elev(ids[ids.index(c['level']) + 1])))
            ok('column')
        except Exception as e:
            fail('column (family)', e)
            try:
                hw = c['w'] / 2.0
                direct_shape(BuiltInCategory.OST_Columns, [prism([(c['x'] - hw, c['y'] - hw), (c['x'] + hw, c['y'] - hw), (c['x'] + hw, c['y'] + hw), (c['x'] - hw, c['y'] + hw)],
                                                                 lv_elev(c['level']), c['h'], 'Concrete')], 'Column 600x600')
                ok('column (directshape)')
            except Exception as e2:
                fail('column', e2)


# ------------------------------------------------------------------ ramps
def ramp_sections(r, n_arc=24):
    C = r['center']; rin, rout, rox = r['r_in'], r['r_out'], r['r_out_x']
    L1 = C[1] - r['y_start']; La = math.pi / 2 * r['r_cl']; L2 = C[0] - r['x_end']; LT = L1 + La + L2
    secs = []
    for k in range(3):
        y = r['y_start'] + L1 * k / 2.0
        secs.append(((C[0] + rin, y), (C[0] + rox, y), L1 * k / 2.0))
    for i in range(1, n_arc + 1):
        a = math.pi / 2 * i / n_arc
        secs.append(((C[0] + rin * math.cos(a), C[1] + rin * math.sin(a)), (C[0] + rox * math.cos(a), C[1] + rout * math.sin(a)), L1 + La * i / n_arc))
    for k in range(1, 3):
        x = C[0] - L2 * k / 2.0
        secs.append(((x, C[1] + rin), (x, C[1] + rout), L1 + La + L2 * k / 2.0))
    return secs, LT


def build_ramps():
    for r in M['ramps']:
        try:
            secs, LT = ramp_sections(r)
            z = lambda s: r['z0'] + (r['z1'] - r['z0']) * s / LT
            geo = mesh_solid(band_tris([(a, b, z(s) - r['thk'], z(s)) for a, b, s in secs]), 'Ramp concrete')
            for side in (0, 1):
                ks = []
                for a, b, s in secs:
                    e0 = a if side == 0 else b
                    o = b if side == 0 else a
                    d = math.hypot(o[0] - e0[0], o[1] - e0[1])
                    e1 = (e0[0] + (o[0] - e0[0]) * 0.2 / d, e0[1] + (o[1] - e0[1]) * 0.2 / d)
                    ks.append((e0, e1, z(s), z(s) + r['kerb_h']))
                geo += mesh_solid(band_tris(ks), 'Concrete')
            ds = direct_shape(BuiltInCategory.OST_Ramps, geo, r['name'])
            comment(ds, '%s - centre-line %.2f m, slope %.1f %%' % (r['name'], r['centerline_length'], r['slope_pct']))
            ok('ramp')
        except Exception as e:
            fail('ramp', e)


# ------------------------------------------------------------------ stairs
def stair_flight_profile(n, rh, t, d=0.22):
    run = (n - 1) * t
    prof = [(0.0, 0.0)]
    for k in range(n):
        prof.append((k * t, (k + 1) * rh))
        if k < n - 1:
            prof.append(((k + 1) * t, (k + 1) * rh))
    u0 = run - (n * rh - d) * t / rh
    prof += [(run, n * rh - d), (max(u0, 0.05), 0.0)]
    return prof


def build_stairs_native(st):
    """Native Revit stairs (two straight runs + automatic landing). Raises on failure."""
    base, top = LEVEL[st['from_level']], LEVEL[st['to_level']]
    scope = StairsEditScope(doc, 'Stairs')
    try:
        sid = scope.Start(base.Id, top.Id)
        t = Transaction(doc, 'Stair runs')
        t.Start()
        try:
            stairs = doc.GetElement(sid)
            set_param(stairs, BuiltInParameter.STAIRS_DESIRED_NUMBER_OF_RISERS, st['risers'])
            set_param(stairs, BuiltInParameter.STAIRS_ACTUAL_TREAD_DEPTH, ft(st['tread']))
            f1, f2 = st['flights']
            ym1 = (f1['y0'] + f1['y1']) / 2.0
            ym2 = (f2['y0'] + f2['y1']) / 2.0
            # run elevations are relative to the stair base (same convention as StairsRun.TopElevation)
            run1 = StairsRun.CreateStraightRun(doc, sid, Line.CreateBound(XYZ(ft(f1['x_low']), ft(ym1), 0.0), XYZ(ft(f1['x_high']), ft(ym1), 0.0)),
                                               StairsRunJustification.Center)
            z2 = run1.TopElevation
            run2 = StairsRun.CreateStraightRun(doc, sid, Line.CreateBound(XYZ(ft(f2['x_low']), ft(ym2), z2), XYZ(ft(f2['x_high']), ft(ym2), z2)),
                                               StairsRunJustification.Center)
            for rn, f in ((run1, f1), (run2, f2)):
                try:
                    rn.ActualRunWidth = ft(f['y1'] - f['y0'])
                except Exception:
                    pass
            StairsLanding.CreateAutomaticLanding(doc, run1.Id, run2.Id)
            if abs(run2.TopElevation - (top.Elevation - base.Elevation)) > 0.05:
                raise Exception('stair does not reach the upper level (%.2f ft)' % run2.TopElevation)
            t.Commit()
        except Exception:
            t.RollBack()
            scope.Cancel()
            raise
        scope.Commit(SwallowWarnings())
        return sid
    finally:
        try:
            scope.Dispose()
        except Exception:
            pass


def build_stairs():
    for st in M['stairs']:
        try:
            build_stairs_native(st)
            ok('stair (native)')
            continue
        except Exception as e:
            fail('stair (native, falling back to DirectShape)', e)
        try:
            with Tx('Stair fallback'):
                geo = []
                for fl in st['flights']:
                    n = fl['risers']; rh = (fl['z1'] - fl['z0']) / n
                    tx = 1.0 if fl['x_high'] > fl['x_low'] else -1.0
                    nvec = (0.0, -tx, 0.0)
                    oy = fl['y1'] if nvec[1] < 0 else fl['y0']
                    geo.append(vprism(stair_flight_profile(n, rh, st['tread']), (fl['x_low'], oy, fl['z0']), (tx, 0, 0), nvec, fl['y1'] - fl['y0'], 'Concrete'))
                ld = st['landing']
                geo.append(prism([(ld['x0'], ld['y0']), (ld['x1'], ld['y0']), (ld['x1'], ld['y1']), (ld['x0'], ld['y1'])], ld['z'] - ld['thk'], ld['thk'], 'Concrete'))
                direct_shape(BuiltInCategory.OST_Stairs, geo, st['name'])
            ok('stair (directshape)')
        except Exception as e:
            fail('stair', e)


# ------------------------------------------------------------------ lifts
def build_lifts():
    DW, DH = 1.1, 2.1
    storeys = [L for L in M['levels'] if L['id'] != 'L06']
    for b in M['lift_banks']:
        X0, Y0, X1, Y1 = b['outer']; t = b['wall_t']; cars = b['cars']; ztop = b['z1']
        def wl(p0, p1, lid, h, base=0.0):
            try:
                w = Wall.Create(doc, Line.CreateBound(P(p0[0], p0[1]), P(p1[0], p1[1])), WT['rc'], LEVEL[lid].Id, ft(h), ft(base), False, True)
                comment(w, b['name'] + ' shaft wall')
                ok('lift shaft wall')
            except Exception as e:
                fail('lift shaft wall', e)
        H = ztop
        if b['door_side'] == 'S':
            wl((X0, Y1 - t / 2), (X1, Y1 - t / 2), 'L00', H)
            wl((X0 + t / 2, Y0), (X0 + t / 2, Y1 - t), 'L00', H)
            wl((X1 - t / 2, Y0), (X1 - t / 2, Y1 - t), 'L00', H)
            for i in range(len(cars) - 1):
                xm = (cars[i][2] + cars[i + 1][0]) / 2.0
                wl((xm, Y0 + t), (xm, Y1 - t), 'L00', H)
            spans = [((c[0] + c[2]) / 2 - DW / 2, (c[0] + c[2]) / 2 + DW / 2) for c in cars]
            lo, hi = X0 + t, X1 - t
            seg = lambda a0, a1: ((a0, Y0 + t / 2), (a1, Y0 + t / 2))
        else:
            wl((X0 + t / 2, Y0), (X0 + t / 2, Y1), 'L00', H)
            wl((X0 + t, Y0 + t / 2), (X1, Y0 + t / 2), 'L00', H)
            wl((X0 + t, Y1 - t / 2), (X1, Y1 - t / 2), 'L00', H)
            for i in range(len(cars) - 1):
                ym = (cars[i][3] + cars[i + 1][1]) / 2.0
                wl((X0 + t, ym), (X1 - t, ym), 'L00', H)
            spans = [((c[1] + c[3]) / 2 - DW / 2, (c[1] + c[3]) / 2 + DW / 2) for c in cars]
            lo, hi = Y0 + t, Y1 - t
            seg = lambda a0, a1: ((X1 - t / 2, a0), (X1 - t / 2, a1))
        for L in storeys:
            edges = [lo] + [v for sp in spans for v in sp] + [hi]
            for i in range(0, len(edges), 2):
                if edges[i + 1] - edges[i] > 0.05:
                    p0, p1 = seg(edges[i], edges[i + 1])
                    wl(p0, p1, L['id'], L['height'])
            for a0, a1 in spans:
                p0, p1 = seg(a0, a1)
                wl(p0, p1, L['id'], L['height'] - DH, DH)
                try:
                    if b['door_side'] == 'S':
                        pts = [(a0, Y0 + t / 2 - 0.03), (a1, Y0 + t / 2 - 0.03), (a1, Y0 + t / 2 + 0.03), (a0, Y0 + t / 2 + 0.03)]
                    else:
                        pts = [(X1 - t / 2 - 0.03, a0), (X1 - t / 2 + 0.03, a0), (X1 - t / 2 + 0.03, a1), (X1 - t / 2 - 0.03, a1)]
                    direct_shape(BuiltInCategory.OST_Doors, [prism(pts, L['elev'], DH, 'Steel')], b['name'] + ' landing door 1100x2100')
                    ok('lift door')
                except Exception as e:
                    fail('lift door', e)
        p0, p1 = seg(lo, hi)
        wl(p0, p1, 'L06', ztop - lv_elev('L06'))
        for i, c in enumerate(cars):
            try:
                pts = [(c[0] + 0.1, c[1] + 0.1), (c[2] - 0.1, c[1] + 0.1), (c[2] - 0.1, c[3] - 0.1), (c[0] + 0.1, c[3] - 0.1)]
                direct_shape(BuiltInCategory.OST_SpecialityEquipment, [prism(pts, 0.05, 2.4, 'Steel')], '%s - lift car %d' % (b['name'], i + 1))
                ok('lift car')
            except Exception as e:
                fail('lift car', e)


# ------------------------------------------------------------------ escalators
def build_escalators():
    for e in M['escalators']:
        try:
            H = e['z1'] - e['z0']; Lp = e['a1'] - e['a0']
            Li = H / math.tan(math.radians(e['angle'])); lb = (Lp - Li) / 2.0
            bottom = e['a1'] if e['bottom_end'] == 'max' else e['a0']
            sgn = -1.0 if e['bottom_end'] == 'max' else 1.0
            if e['axis'] == 'y':
                tv = (0.0, sgn, 0.0); nv = (sgn, 0.0, 0.0)
                o = ((e['b0'] if nv[0] > 0 else e['b1']), bottom, e['z0'])
            else:
                tv = (sgn, 0.0, 0.0); nv = (0.0, -sgn, 0.0)
                o = (bottom, (e['b0'] if nv[1] > 0 else e['b1']), e['z0'])
            W = e['b1'] - e['b0']
            truss = [(0, 0), (lb, 0), (lb + Li, H), (Lp, H), (Lp, H - 1.0), (lb + Li, H - 1.0), (lb, -1.0), (0, -1.0)]
            bal = [(lb * 0.5, 0.0), (lb, 0.0), (lb + Li, H), (Lp - lb * 0.5, H), (Lp - lb * 0.5, H + 1.0), (lb + Li, H + 1.0), (lb, 1.0), (lb * 0.5, 1.0)]
            geo = [vprism(truss, o, tv, nv, W, 'Steel')]
            for off in (0.0, W - 0.05):
                oo = (o[0] + nv[0] * off, o[1] + nv[1] * off, o[2])
                geo.append(vprism(bal, oo, tv, nv, 0.05, 'Glass'))
            direct_shape(BuiltInCategory.OST_SpecialityEquipment, geo, e['name'])
            ok('escalator')
        except Exception as ex:
            fail('escalator', ex)


# ------------------------------------------------------------------ cinema
def sector(c, r0, r1, a0, a1, n=24):
    A = [math.radians(a0 + (a1 - a0) * i / float(n)) for i in range(n + 1)]
    return [(c[0] + r0 * math.cos(a), c[1] + r0 * math.sin(a)) for a in A] + [(c[0] + r1 * math.cos(a), c[1] + r1 * math.sin(a)) for a in A[::-1]]


def build_cinema():
    for r in M['risers']:
        try:
            direct_shape(BuiltInCategory.OST_Floors, [prism(r['poly'], r['z0'], r['z1'] - r['z0'], 'Stadium riser')],
                         'Stadium seating riser %s row %d' % (r['theatre'], r['row']))
            ok('stadium riser')
        except Exception as e:
            fail('stadium riser', e)
    for s in M['seats']:
        try:
            a = math.radians(s['rot']); ca, sa = math.cos(a), math.sin(a)
            def tr(pts):
                return [(s['x'] + ca * u - sa * v, s['y'] + sa * u + ca * v) for u, v in pts]
            geo = [prism(tr([(-0.62, -0.26), (-0.12, -0.26), (-0.12, 0.26), (-0.62, 0.26)]), s['z'], 0.46, 'Seat fabric'),
                   prism(tr([(-0.16, -0.27), (0.0, -0.27), (0.0, 0.27), (-0.16, 0.27)]), s['z'], 1.0, 'Seat fabric'),
                   prism(tr([(-0.62, 0.26), (-0.05, 0.26), (-0.05, 0.30), (-0.62, 0.30)]), s['z'], 0.65, 'Seat fabric')]
            direct_shape(BuiltInCategory.OST_Furniture, geo, 'Cinema seat %s row %d' % (s['theatre'], s['row']))
            ok('cinema seat')
        except Exception as e:
            fail('cinema seat', e)
    for s in M['screens']:
        try:
            direct_shape(BuiltInCategory.OST_GenericModel, [prism(sector(s['center'], s['r'], s['r'] + s['thk'], s['a0'], s['a1']), s['z0'], s['h'], 'Screen')], s['name'])
            ok('screen')
        except Exception as e:
            fail('screen', e)


def build_doors():
    for d in M['doors']:
        try:
            x, y = d['p']; w = d['w']
            if d['axis'] == 'y':
                pts = [(x - 0.03, y - w / 2), (x + 0.03, y - w / 2), (x + 0.03, y + w / 2), (x - 0.03, y + w / 2)]
            else:
                pts = [(x - w / 2, y - 0.03), (x + w / 2, y - 0.03), (x + w / 2, y + 0.03), (x - w / 2, y + 0.03)]
            direct_shape(BuiltInCategory.OST_Doors, [prism(pts, lv_elev(d['level']), d['h'], 'Door')], d['name'])
            ok('door')
        except Exception as e:
            fail('door', e)


def build_rooms():
    doc.Regenerate()
    for sp in M['spaces']:
        try:
            pts = sp['poly']
            cx = sum(p[0] for p in pts) / len(pts)
            cy = sum(p[1] for p in pts) / len(pts)
            rm = doc.Create.NewRoom(LEVEL[sp['level']], UV(ft(cx), ft(cy)))
            rm.Name = sp['name']
            ok('room')
        except Exception as e:
            fail('room', e)


# ------------------------------------------------------------------ main
def main():
    log('Entertainment Complex builder - model: %s' % MODEL_PATH)
    tg = TransactionGroup(doc, 'Build Entertainment Complex')
    tg.Start()
    with Tx('Materials, types, levels'):
        for n, c, t in [('Concrete', (191, 191, 186), 0), ('Blockwork', (237, 230, 214), 0), ('Glass', (140, 191, 230), 60),
                        ('Asphalt', (84, 92, 97), 0), ('Parking bay paint', (204, 219, 242), 0), ('Ramp concrete', (242, 204, 89), 0),
                        ('Steel', (140, 148, 158), 0), ('Seat fabric', (179, 20, 26), 0), ('Stadium riser', (89, 46, 38), 0),
                        ('Screen', (250, 250, 250), 0), ('Door', (140, 97, 51), 0)]:
            material(n, c, t)
        WT['block'] = wall_type('EC Blockwork 200', 0.20, 'Blockwork')
        WT['partition'] = wall_type('EC Partition 150', 0.15, 'Blockwork')
        WT['glazed'] = wall_type('EC Glazed partition 100', 0.10, 'Glass')
        WT['parapet'] = wall_type('EC Parapet 200', 0.20, 'Blockwork')
        WT['spine'] = wall_type('EC Stair spine 1400', 1.40, 'Concrete')
        WT['rc'] = wall_type('EC RC shaft wall 200', 0.20, 'Concrete')
        WT['balustrade'] = wall_type('EC Glass balustrade 60', 0.06, 'Glass')
        FTY['slab'] = floor_type('EC RC slab 200', 0.20, 'Concrete')
        FTY['ground'] = floor_type('EC Ground slab 250', 0.25, 'Concrete')
        FTY['roof'] = floor_type('EC Roof slab 200', 0.20, 'Concrete')
        FTY['drive'] = floor_type('EC Drive aisle 20', 0.02, 'Asphalt')
        build_levels()
        build_grids()
    for name, fn in [('Walls', build_walls), ('Floors and slabs', build_slabs), ('Columns', build_columns),
                     ('Ramps', build_ramps), ('Lifts', build_lifts), ('Escalators', build_escalators),
                     ('Railings', build_railings), ('Doors', build_doors), ('Cinema', build_cinema)]:
        log('Building %s ...' % name)
        try:
            with Tx(name):
                fn()
        except Exception as e:
            log('Phase %s failed: %s' % (name, traceback.format_exc()))
    log('Building Stairs ...')
    build_stairs()
    try:
        with Tx('Rooms'):
            build_rooms()
    except Exception:
        log('Rooms failed: %s' % traceback.format_exc())
    view3d = None
    with Tx('3D view'):
        vft3 = [v for v in collect(ViewFamilyType) if v.ViewFamily == ViewFamily.ThreeDimensional][0]
        view3d = View3D.CreateIsometric(doc, vft3.Id)
        try:
            view3d.Name = '3D - Entertainment Complex'
        except Exception:
            pass
        try:
            view3d.DetailLevel = ViewDetailLevel.Fine
            view3d.DisplayStyle = DisplayStyle.ShadingWithEdges
        except Exception:
            pass
    tg.Assimilate()

    # ------------------------------------------------ save RVT and export DWF / DWFx
    rvt = os.path.join(OUT_DIR, 'Entertainment_Complex.rvt')
    try:
        so = SaveAsOptions()
        so.OverwriteExistingFile = True
        doc.SaveAs(rvt, so)
        log('Saved %s' % rvt)
    except Exception as e:
        log('SaveAs failed (%s) - use File > Save As manually.' % e)
    try:
        vs = ViewSet()
        vs.Insert(view3d)
        for v in PLAN_VIEWS:
            vs.Insert(v)
        o = DWFExportOptions()
        o.MergedViews = True
        o.ExportObjectData = True
        doc.Export(OUT_DIR, 'Entertainment_Complex', vs, o)
        log('Exported %s' % os.path.join(OUT_DIR, 'Entertainment_Complex.dwf'))
        ox = DWFXExportOptions()
        ox.MergedViews = True
        ox.ExportObjectData = True
        doc.Export(OUT_DIR, 'Entertainment_Complex', vs, ox)
        log('Exported %s' % os.path.join(OUT_DIR, 'Entertainment_Complex.dwfx'))
    except Exception as e:
        log('DWF export failed (%s) - use File > Export > DWF/DWFx manually.' % e)

    log('Created: ' + ', '.join('%s=%d' % kv for kv in sorted(STATS.items())))
    if ERRORS:
        log('Failures: ' + ', '.join('%s=%d' % kv for kv in sorted(ERRORS.items())))
    try:
        with io.open(os.path.join(OUT_DIR, 'build_revit_model.log'), 'w', encoding='utf-8') as fh:
            fh.write(u'\n'.join(u'%s' % l for l in LOG))
    except Exception:
        pass
    return '\n'.join(LOG)


FTY = {}
RESULT = main()
OUT = RESULT     # Dynamo output
