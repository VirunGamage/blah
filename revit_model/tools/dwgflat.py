"""Flatten LibreDWG JSON output into world-space primitives (with block expansion)."""
import json, math, sys

def ref(h):
    return h[-1] if h else None

class DWG:
    def __init__(self, path):
        d = json.load(open(path))
        self.objs = d['OBJECTS']
        self.by_handle = {o['handle'][2]: o for o in self.objs if 'handle' in o}
        self.layers = {}
        for o in self.objs:
            if o.get('object') == 'LAYER':
                self.layers[o['handle'][2]] = (o['name'], o.get('color', {}).get('index', 7))
        self.blocks = {o['handle'][2]: o for o in self.objs if o.get('object') == 'BLOCK_HEADER'}
        self.ms = next(o for o in self.blocks.values() if o['name'].lower() == '*model_space')

    def layer_name(self, e):
        return self.layers.get(ref(e.get('layer')), ('?', 7))[0]

    def layer_color(self, name):
        for n, c in self.layers.values():
            if n == name:
                return c
        return 7

    def flatten(self, top_filter=None):
        out = []
        for h in self.ms.get('entities', []):
            e = self.by_handle.get(ref(h))
            if e is None:
                continue
            lay = self.layer_name(e)
            src = {'top_handle': e['handle'][2], 'top_type': e.get('entity'), 'top_layer': lay}
            if e.get('entity') == 'INSERT':
                bh = self.blocks.get(ref(e.get('block_header')))
                src['block'] = bh['name'] if bh else None
            self._emit(e, [1, 0, 0, 0, 1, 0], lay, src, out, 0)
        return out

    def _emit(self, e, M, parent_layer, src, out, depth):
        t = e.get('entity')
        lay = self.layer_name(e)
        if lay == '0':
            lay = parent_layer
        ci = e.get('color', {}).get('index', 256)
        def tp(p):
            x, y = p[0], p[1]
            return (M[0]*x + M[1]*y + M[2], M[3]*x + M[4]*y + M[5])
        base = dict(layer=lay, color=ci, **src)
        if t == 'LINE':
            out.append(dict(base, kind='line', pts=[tp(e['start']), tp(e['end'])]))
        elif t in ('ARC', 'CIRCLE'):
            c, r = e['center'], e['radius']
            a0, a1 = (e.get('start_angle', 0), e.get('end_angle', 2*math.pi))
            if e.get('extrusion', [0, 0, 1])[2] < 0:
                c = [-c[0], c[1]]; a0, a1 = math.pi - a1, math.pi - a0
            if a1 <= a0:
                a1 += 2*math.pi
            n = max(8, int((a1 - a0) / (math.pi/36)))
            pts = [tp((c[0] + r*math.cos(a0 + (a1-a0)*i/n), c[1] + r*math.sin(a0 + (a1-a0)*i/n))) for i in range(n+1)]
            out.append(dict(base, kind='arc', pts=pts, center=tp(c), radius=r*math.hypot(M[0], M[3]), a0=a0, a1=a1))
        elif t == 'LWPOLYLINE':
            pts = e.get('points', [])
            bul = e.get('bulges', []) or [0]*len(pts)
            closed = bool(e.get('flag', 0) & 512) or bool(e.get('flag', 0) & 1)
            seq = []
            n = len(pts)
            rng = n if closed else n-1
            for i in range(n):
                seq.append(tuple(pts[i]))
                if i < rng and i < len(bul) and abs(bul[i]) > 1e-9:
                    p0, p1 = pts[i], pts[(i+1) % n]
                    b = bul[i]
                    ang = 4*math.atan(b)
                    chord = math.hypot(p1[0]-p0[0], p1[1]-p0[1])
                    r = chord / (2*math.sin(ang/2))
                    mx, my = (p0[0]+p1[0])/2, (p0[1]+p1[1])/2
                    d = r*math.cos(ang/2)
                    nx, ny = -(p1[1]-p0[1])/chord, (p1[0]-p0[0])/chord
                    cx, cy = mx + nx*d, my + ny*d
                    s0 = math.atan2(p0[1]-cy, p0[0]-cx)
                    k = 12
                    for j in range(1, k):
                        a = s0 + ang*j/k
                        seq.append((cx + abs(r)*math.cos(a) if r > 0 else cx + abs(r)*math.cos(a), cy + abs(r)*math.sin(a)))
            if closed and seq:
                seq.append(seq[0])
            out.append(dict(base, kind='poly', pts=[tp(p) for p in seq], closed=closed))
        elif t in ('TEXT', 'MTEXT'):
            txt = e.get('text_value') or e.get('text') or ''
            out.append(dict(base, kind='text', pts=[tp(e['ins_pt'])], text=txt, h=e.get('height', e.get('text_height', 1))))
        elif t == 'SOLID':
            ps = [tp(e[k]) for k in ('corner1', 'corner2', 'corner4', 'corner3')]
            out.append(dict(base, kind='solid', pts=ps + [ps[0]]))
        elif t == 'INSERT' and depth < 8:
            bh = self.blocks.get(ref(e.get('block_header')))
            if not bh:
                return
            ip = e['ins_pt']; sc = e.get('scale', [1, 1, 1]); rot = e.get('rotation', 0)
            bp = bh.get('base_pt', [0, 0, 0])
            ex = e.get('extrusion', [0, 0, 1])
            sx = sc[0] * (-1 if ex[2] < 0 else 1)
            cr, sr = math.cos(rot), math.sin(rot)
            # local: p' = R*S*(p-bp) + ip   (with OCS mirror for negative extrusion on x)
            L = [cr*sx, -sr*sc[1], 0, sr*sx, cr*sc[1], 0]
            ipx = -ip[0] if ex[2] < 0 else ip[0]
            L[2] = ipx - (L[0]*bp[0] + L[1]*bp[1])
            L[5] = ip[1] - (L[3]*bp[0] + L[4]*bp[1])
            if ex[2] < 0:
                L = [-L[0], -L[1], -L[2], L[3], L[4], L[5]]
            N = [M[0]*L[0] + M[1]*L[3], M[0]*L[1] + M[1]*L[4], M[0]*L[2] + M[1]*L[5] + M[2],
                 M[3]*L[0] + M[4]*L[3], M[3]*L[1] + M[4]*L[4], M[3]*L[2] + M[4]*L[5] + M[5]]
            out.append(dict(base, kind='insert', pts=[tp(ip)], block=bh['name'], rotation=rot, scale=sc, depth=depth, M=N))
            for h in bh.get('entities', []):
                c = self.by_handle.get(ref(h))
                if c is not None:
                    self._emit(c, N, lay, src, out, depth+1)

if __name__ == '__main__':
    d = DWG(sys.argv[1])
    prims = d.flatten()
    json.dump({'prims': prims, 'layers': {n: c for n, c in d.layers.values()}}, open(sys.argv[2], 'w'))
    print(len(prims))
