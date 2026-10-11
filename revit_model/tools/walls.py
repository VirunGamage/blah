"""Merge DWG double-line walls into centreline wall segments."""
import math, collections

def segs_from_prims(prims):
    out = []
    for p in prims:
        pts = p['pts']
        for i in range(len(pts) - 1):
            (x0, y0), (x1, y1) = pts[i], pts[i + 1]
            if math.hypot(x1 - x0, y1 - y0) > 0.02:
                out.append((x0, y0, x1, y1))
    return out

def merge(segs, pair_tol=0.16, ang_tol_deg=1.0, gap_tol=0.12, min_len=0.35):
    groups = collections.defaultdict(list)
    for x0, y0, x1, y1 in segs:
        a = math.atan2(y1 - y0, x1 - x0) % math.pi
        if a > math.pi - math.radians(ang_tol_deg):
            a -= math.pi
        key = round(math.degrees(a) / ang_tol_deg)
        groups[key].append((x0, y0, x1, y1))
    walls = []
    for key, ss in groups.items():
        a = math.radians(key * ang_tol_deg)
        # refine angle by mean of members
        angs = []
        for x0, y0, x1, y1 in ss:
            t = math.atan2(y1 - y0, x1 - x0) % math.pi
            if t - a > math.pi / 2: t -= math.pi
            if a - t > math.pi / 2: t += math.pi
            angs.append(t)
        a = sum(angs) / len(angs)
        d = (math.cos(a), math.sin(a)); n = (-d[1], d[0])
        items = []
        for x0, y0, x1, y1 in ss:
            o = ((x0 * n[0] + y0 * n[1]) + (x1 * n[0] + y1 * n[1])) / 2
            t0 = x0 * d[0] + y0 * d[1]; t1 = x1 * d[0] + y1 * d[1]
            items.append((o, min(t0, t1), max(t0, t1)))
        items.sort()
        # cluster offsets
        clusters = []
        for it in items:
            if clusters and it[0] - clusters[-1][-1][0] <= pair_tol:
                clusters[-1].append(it)
            else:
                clusters.append([it])
        for cl in clusters:
            ivs = sorted((t0, t1, o) for o, t0, t1 in cl)
            merged = []
            for t0, t1, o in ivs:
                if merged and t0 <= merged[-1][1] + gap_tol:
                    m = merged[-1]; m[1] = max(m[1], t1); m[2].append(o)
                else:
                    merged.append([t0, t1, [o]])
            for t0, t1, os_ in merged:
                if t1 - t0 < min_len:
                    continue
                omin, omax = min(os_), max(os_)
                o = (omin + omax) / 2
                th = omax - omin
                p0 = (d[0] * t0 + n[0] * o, d[1] * t0 + n[1] * o)
                p1 = (d[0] * t1 + n[0] * o, d[1] * t1 + n[1] * o)
                walls.append({'p0': p0, 'p1': p1, 'drawn_thk': th, 'n_lines': len(os_)})
    return walls
