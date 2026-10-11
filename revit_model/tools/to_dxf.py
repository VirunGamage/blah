import sys, pickle, numpy as np, ezdxf
from ezdxf import colors
tris = pickle.load(open(sys.argv[1], 'rb'))
doc = ezdxf.new('R2018', setup=True); doc.units = ezdxf.units.M
msp = doc.modelspace()
LAY = {'IfcWall': 'A-WALL', 'IfcCurtainWall': 'A-GLAZ-CWMG', 'IfcColumn': 'S-COLS', 'IfcSlab': 'A-FLOR', 'IfcCovering': 'A-FLOR-DRIVE',
       'IfcBuildingElementProxy': 'A-SPCL', 'IfcRampFlight': 'A-RAMP', 'IfcStairFlight': 'A-STRS', 'IfcRailing': 'A-RAIL',
       'IfcTransportElement': 'A-CONV', 'IfcDoor': 'A-DOOR', 'IfcFurniture': 'I-FURN-SEAT'}
for cls, name, v, fa, mats, mids in tris:
    if cls == 'IfcSpace': continue
    lay = LAY.get(cls, 'A-MISC')
    if name and 'Parking stall' in name: lay = 'A-PARK-STALL'
    if name and 'Screen' in name: lay = 'I-SCRN'
    if lay not in doc.layers: doc.layers.add(lay)
    r, g, b, t = mats[0] if mats else (0.7, 0.7, 0.7, 0)
    m = msp.add_mesh(dxfattribs={'layer': lay, 'true_color': colors.rgb2int((int(r * 255), int(g * 255), int(b * 255)))})
    if t and t > 0.2: m.transparency = min(0.8, t)
    with m.edit_data() as md:
        md.vertices = [tuple(map(float, p)) for p in v]
        md.faces = [tuple(map(int, f_)) for f_ in fa]
doc.set_modelspace_vport(height=60, center=(37, 12))
doc.saveas(sys.argv[2])
print('ok', len(msp))
