import json, sys, math
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
from matplotlib.patches import Polygon as MP, Rectangle
m = json.load(open(sys.argv[1]))
lv = [l for l in m['levels']]
fig, axs = plt.subplots(4, 2, figsize=(26, 34)); axs = axs.ravel()
for ax, L in zip(axs, lv):
    lid = L['id']; ax.set_title('%s %s (+%.1f)' % (lid, L['name'], L['elev']))
    for s in m['slabs']:
        if s['level'] != lid: continue
        ax.add_patch(MP(s['outer'], closed=True, fc='#dddddd' if s['kind'] == 'floor' else '#ccddee', ec='k', lw=0.5, alpha=0.6))
        for h in s['holes']: ax.add_patch(MP(h, closed=True, fc='white', ec='r', lw=0.8))
    for s in m['surfaces']:
        if s['level'] == lid: ax.add_patch(MP(s['poly'], closed=True, fc='#99cc99', ec='g', lw=0.5, alpha=0.5))
    for b in m['parking_bays']:
        if b['level'] == lid: ax.add_patch(MP(b['poly'], closed=True, fc='none', ec='m', lw=0.6))
    for w in m['walls']:
        if w['level'] != lid: continue
        c = {'masonry': 'k', 'glazed': 'c', 'curtain': 'b', 'parapet': 'orange'}[w['kind']]
        ax.plot([w['p0'][0], w['p1'][0]], [w['p0'][1], w['p1'][1]], color=c, lw=max(0.8, w['thk'] * 8), solid_capstyle='butt')
    for w in m['arc_walls']:
        if w['level'] != lid: continue
        a = [math.radians(w['a0'] + (w['a1'] - w['a0']) * i / 20) for i in range(21)]
        ax.plot([w['center'][0] + w['r'] * math.cos(t) for t in a], [w['center'][1] + w['r'] * math.sin(t) for t in a], 'c', lw=1.5)
    for r in m['railings']:
        if r['level'] == lid: ax.plot([r['p0'][0], r['p1'][0]], [r['p0'][1], r['p1'][1]], color='lime', lw=2)
    for c in m['columns']:
        if c['level'] == lid: ax.add_patch(Rectangle((c['x'] - 0.3, c['y'] - 0.3), 0.6, 0.6, fc='k'))
    for b in m['lift_banks']:
        x0, y0, x1, y1 = b['outer']; ax.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, fc='none', ec='purple', lw=2))
        for c in b['cars']: ax.add_patch(Rectangle((c[0], c[1]), c[2] - c[0], c[3] - c[1], fc='plum', ec='purple'))
    for st in m['stairs']:
        if st['from_level'] != lid: continue
        for f in st['flights']:
            ax.add_patch(Rectangle((min(f['x_low'], f['x_high']), f['y0']), abs(f['x_high'] - f['x_low']), f['y1'] - f['y0'], fc='yellow', ec='brown'))
        ld = st['landing']; ax.add_patch(Rectangle((ld['x0'], ld['y0']), ld['x1'] - ld['x0'], ld['y1'] - ld['y0'], fc='khaki', ec='brown'))
    for e in m['escalators']:
        if e['from_level'] != lid: continue
        if e['axis'] == 'y': ax.add_patch(Rectangle((e['b0'], e['a0']), e['b1'] - e['b0'], e['a1'] - e['a0'], fc='teal', ec='k', alpha=0.6))
        else: ax.add_patch(Rectangle((e['a0'], e['b0']), e['a1'] - e['a0'], e['b1'] - e['b0'], fc='teal', ec='k', alpha=0.6))
    for r in m['ramps']:
        if r['from_level'] == lid: ax.add_patch(MP(r['footprint'], closed=True, fc='gold', ec='orange', alpha=0.6))
    for r in m['risers']:
        if r['level'] == lid: ax.add_patch(MP(r['poly'], closed=True, fc=(0.5, 0.2, 0.2, 0.08 + 0.05 * r['row']), ec='brown', lw=0.3))
    for s in m['seats']:
        if s['level'] == lid: ax.plot(s['x'], s['y'], 'r.', ms=2)
    for s in m['screens']:
        if s['level'] != lid: continue
        a = [math.radians(s['a0'] + (s['a1'] - s['a0']) * i / 20) for i in range(21)]
        ax.plot([s['center'][0] + s['r'] * math.cos(t) for t in a], [s['center'][1] + s['r'] * math.sin(t) for t in a], 'w', lw=4)
        ax.plot([s['center'][0] + s['r'] * math.cos(t) for t in a], [s['center'][1] + s['r'] * math.sin(t) for t in a], 'k', lw=2)
    for d in m['doors']:
        if d['level'] == lid: ax.plot(*d['p'], 'bs', ms=5)
    for sp in m['spaces']:
        if sp['level'] == lid:
            cx = sum(p[0] for p in sp['poly']) / len(sp['poly']); cy = sum(p[1] for p in sp['poly']) / len(sp['poly'])
            ax.text(cx, cy, sp['name'], fontsize=8, ha='center')
    ax.set_xlim(-5, 79); ax.set_ylim(-13, 39); ax.set_aspect('equal'); ax.grid(True, lw=0.2)
fig.tight_layout(); fig.savefig(sys.argv[2], dpi=45)
