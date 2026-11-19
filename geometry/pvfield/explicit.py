"""Explicit fixed-mount tables: front-view anchors, no packing or guessed support."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math

from shapely.geometry import LineString, Polygon

from geometry.scene.mesh import _number, _triple
from geometry.scene.surface_plane import SurfacePlane
from geometry.scene3d.height import module_axes, module_corners

EXPLICIT_LAYOUT_VERSION = "rawibumi.explicit_table_layout.v1"
# Left/right are as seen facing the module FRONT, not the internal +row axis.
ANCHORS = {
    "lower_left": (0., 0.), "lower_center": (.5, 0.), "lower_right": (1., 0.),
    "left_center": (0., .5), "center": (.5, .5), "right_center": (1., .5),
    "upper_left": (0., 1.), "upper_center": (.5, 1.), "upper_right": (1., 1.),
}


def is_explicit(field):
    return field.get("field_kind") == "explicit_layout"


def table_axes(azimuth_deg, tilt_deg):
    row, down, normal = module_axes(azimuth_deg, tilt_deg)
    return tuple(-v for v in row), tuple(-v for v in down), normal


def table_rectangle(table):
    right, up, _ = table_axes(table["azimuth_deg"], table["tilt_deg"])
    alpha, beta = ANCHORS[table["anchor_convention"]]
    anchor = table["anchor_xyz_m"]
    width, height = table["rectangle"]["width_m"], table["rectangle"]["height_m"]
    return [[anchor[i]+(x-alpha)*width*right[i]+(y-beta)*height*up[i] for i in range(3)]
            for x,y in ((0,1),(1,1),(1,0),(0,0))]


def _centre(table, row, column):
    right, up, _ = table_axes(table["azimuth_deg"], table["tilt_deg"])
    alpha, beta = ANCHORS[table["anchor_convention"]]
    width, height = table["rectangle"]["width_m"], table["rectangle"]["height_m"]
    w,h = table["plane_module_width_m"], table["plane_module_height_m"]
    occupied_width = table["modules_across"]*w+(table["modules_across"]-1)*table["module_gap_across_m"]
    occupied_height = table["modules_up"]*h+(table["modules_up"]-1)*table["module_gap_up_m"]
    x = (.5-alpha)*width-occupied_width/2+w/2+column*(w+table["module_gap_across_m"])
    y = (.5-beta)*height+occupied_height/2-h/2-row*(h+table["module_gap_up_m"])
    return [table["anchor_xyz_m"][i]+x*right[i]+y*up[i] for i in range(3)]


def _check_bounds(points, label):
    if any(not math.isfinite(v) for p in points for v in p):
        raise ValueError(f"{label}: derived coordinates must be finite")
    if any(abs(p[i])>50000 for p in points for i in (0,1)) or any(max(p[i] for p in points)-min(p[i] for p in points)>10000 for i in (0,1)):
        raise ValueError(f"{label}: table XY bounds exceed scene limits")
    if any(not -1000<=p[2]<=10000 for p in points):
        raise ValueError(f"{label}: table elevations must be within [-1000,10000] m")


def _validate_support(corners, support, label):
    shape=Polygon(support['boundary_2d']['vertices'],support['boundary_2d'].get('holes',[]))
    xy=[p[:2] for p in corners]
    area=Polygon(xy)
    projection=area if area.area>1e-10 else LineString(xy)
    if not shape.is_valid or not shape.covers(projection):
        raise ValueError(f"{label}: modules must remain over the usable support, outside holes")
    plane=SurfacePlane.from_surface(support)
    if any(p[2]<plane.elevation_at(p[0],p[1])-1e-9 for p in corners):
        raise ValueError(f"{label}: module penetrates its declared support plane")


def create_explicit_field(scene, definitions, *, pv_field_id, name, tables, provenance):
    """Return canonical field/modules; input Scene and definitions stay untouched."""
    if not all(isinstance(v,str) and v.strip() for v in (pv_field_id,name)):
        raise ValueError("explicit field identity and name must be nonblank strings")
    if not isinstance(tables,list) or not 1<=len(tables)<=2000:
        raise ValueError(f"field {pv_field_id}: expected 1 to 2000 tables")
    if not isinstance(provenance,dict):raise ValueError(f"field {pv_field_id}: provenance must be an object")
    canonical=[];identities=set();total=0
    allowed={'table_id','anchor_xyz_m','anchor_convention','tilt_deg','azimuth_deg','module_definition_revision_id','modules_across','modules_up','module_orientation','module_gap_across_m','module_gap_up_m','rectangle','support_surface_id'}
    required=allowed-{'rectangle','support_surface_id'}
    for source in tables:
        if not isinstance(source,dict) or not required<=source.keys() or set(source)-allowed:
            raise ValueError(f"field {pv_field_id}: missing or unknown table keys")
        t=deepcopy(source);tid=t['table_id'];label=f"field {pv_field_id} table {tid}"
        if not isinstance(tid,str) or not tid.strip() or tid in identities:
            raise ValueError(f"{label}: duplicate or invalid table identity")
        identities.add(tid)
        if t['anchor_convention'] not in ANCHORS:raise ValueError(f"{label}: unknown anchor convention")
        t['anchor_xyz_m']=_triple(t['anchor_xyz_m'],label)
        t['tilt_deg']=_number(t['tilt_deg'],label);t['azimuth_deg']=_number(t['azimuth_deg'],label)
        if not 0<=t['tilt_deg']<=90 or not 0<=t['azimuth_deg']<360:
            raise ValueError(f"{label}: tilt must be in [0,90], azimuth in [0,360)")
        for key in ('modules_across','modules_up'):
            if type(t[key]) is not int or not 1<=t[key]<=50000:raise ValueError(f"{label}: module counts must be positive bounded integers")
        total+=t['modules_across']*t['modules_up']
        if total>50000:raise ValueError(f"{label}: explicit layout exceeds 50000 modules")
        for key in ('module_gap_across_m','module_gap_up_m'):
            t[key]=_number(t[key],label)
            if t[key]<0:raise ValueError(f"{label}: module gaps must be nonnegative")
        definition=definitions.get(t['module_definition_revision_id'])
        if definition is None:raise ValueError(f"{label}: pinned module definition is missing")
        if (definition.get('capability_flags') or {}).get('layout_ready') is False:
            raise ValueError(f"{label}: module definition is not layout ready")
        mechanical=definition.get('mechanical') or {}
        w=_number(mechanical.get('width_m'),label);h=_number(mechanical.get('height_m'),label)
        if min(w,h)<=0:raise ValueError(f"{label}: physical module dimensions must be positive")
        t['physical_module_width_m'],t['physical_module_height_m']=w,h
        if t['module_orientation']=='portrait':pw,ph=w,h
        elif t['module_orientation']=='landscape':pw,ph=h,w
        else:raise ValueError(f"{label}: module orientation must be portrait or landscape")
        t['plane_module_width_m'],t['plane_module_height_m']=pw,ph
        ow=t['modules_across']*pw+(t['modules_across']-1)*t['module_gap_across_m']
        oh=t['modules_up']*ph+(t['modules_up']-1)*t['module_gap_up_m']
        rect=t.get('rectangle',{'width_m':ow,'height_m':oh})
        if not isinstance(rect,dict) or set(rect)!={'width_m','height_m'}:raise ValueError(f"{label}: rectangle requires width_m and height_m")
        rw,rh=(_number(rect[k],label) for k in ('width_m','height_m'))
        if min(rw,rh)<=0 or rw<ow-1e-9 or rh<oh-1e-9:raise ValueError(f"{label}: module occupancy exceeds declared table rectangle")
        t['rectangle']={'width_m':rw,'height_m':rh}
        _check_bounds(table_rectangle(t),label)
        support_id=t.get('support_surface_id')
        if support_id is not None and not any(s['surface_id']==support_id for s in scene.get('surfaces',[])):
            raise ValueError(f"{label}: declared support surface is missing")
        t['support_surface_id']=support_id
        canonical.append(t)
    canonical.sort(key=lambda t:t['table_id'])
    field={'pv_field_id':pv_field_id,'scene_id':scene['scene_id'],'name':name,'field_kind':'explicit_layout','layout_source':'explicit_layout','layout_mode':'fixed_tilt','tables':canonical,'provenance':deepcopy(provenance),'layout_status':'explicit','explicit_layout_version':EXPLICIT_LAYOUT_VERSION,'generated_module_instance_ids':[]}
    supports={s['surface_id']:s for s in scene.get('surfaces',[])};modules=[]
    for index,t in enumerate(canonical):
        for row in range(t['modules_up']):
            for column in range(t['modules_across']):
                centre=_centre(t,row,column)
                corners=module_corners(tuple(centre),t['plane_module_width_m'],t['plane_module_height_m'],t['azimuth_deg'],t['tilt_deg'])
                _check_bounds(corners,f"table {t['table_id']}")
                if t['support_surface_id'] is not None:_validate_support(corners,supports[t['support_surface_id']],f"table {t['table_id']}")
                identity=json.dumps([pv_field_id,t['table_id'],row,column],separators=(',',':'),ensure_ascii=False)
                mid='module-explicit-'+hashlib.sha256(identity.encode()).hexdigest()[:24]
                modules.append({'module_instance_id':mid,'pv_field_id':pv_field_id,'module_definition_revision_id':t['module_definition_revision_id'],'table_id':t['table_id'],'transform':{'position_x_m':centre[0],'position_y_m':centre[1],'position_z_m':centre[2],'rotation_z_deg':t['azimuth_deg'],'rotation_x_deg':0.,'rotation_y_deg':0.,'scale_x':1.,'scale_y':1.,'scale_z':1.},'row_index':row,'column_index':column,'table_index':index,'enabled':True,'metadata':{'position_z_basis':'explicit_table_anchor','explicit_layout_version':EXPLICIT_LAYOUT_VERSION}})
    field['generated_module_instance_ids']=sorted(m['module_instance_id'] for m in modules)
    json.dumps(field,allow_nan=False)
    return field,sorted(modules,key=lambda m:m['module_instance_id'])


def table_for_module(module, field):
    table=next((t for t in field['tables'] if t['table_id']==module.get('table_id')),None)
    if table is None:raise ValueError(f"module {module['module_instance_id']}: explicit table is missing")
    if module['module_definition_revision_id']!=table['module_definition_revision_id']:
        raise ValueError(f"module {module['module_instance_id']}: module revision disagrees with explicit table")
    row,column=module['row_index'],module['column_index']
    if type(row) is not int or type(column) is not int or not 0<=row<table['modules_up'] or not 0<=column<table['modules_across']:
        raise ValueError(f"module {module['module_instance_id']}: explicit grid index is invalid")
    expected=_centre(table,row,column)
    transform=module['transform'];actual=[_number(transform[k],module['module_instance_id']) for k in ('position_x_m','position_y_m','position_z_m')]
    if max(abs(a-b) for a,b in zip(expected,actual))>1e-9 or transform['rotation_z_deg']!=table['azimuth_deg']:
        raise ValueError(f"module {module['module_instance_id']}: stored placement disagrees with explicit table")
    return table


def explicit_module_geometry(module, field, surfaces):
    table=table_for_module(module,field)
    centre=_centre(table,module['row_index'],module['column_index'])
    w,h=table['plane_module_width_m'],table['plane_module_height_m']
    row,down,normal=module_axes(table['azimuth_deg'],table['tilt_deg'])
    corners=module_corners(tuple(centre),w,h,table['azimuth_deg'],table['tilt_deg'])
    support=next((s for s in surfaces if s['surface_id']==table.get('support_surface_id')),None)
    if table.get('support_surface_id') is not None and support is None:raise ValueError(f"table {table['table_id']}: support is missing")
    if support is not None:_validate_support(corners,support,f"table {table['table_id']}")
    plane=SurfacePlane.from_surface(support) if support else None
    clearances=[p[2]-plane.elevation_at(p[0],p[1]) for p in corners] if plane else None
    geometry={'module_instance_id':module['module_instance_id'],'pv_field_id':field['pv_field_id'],'module_definition_revision_id':module['module_definition_revision_id'],'support_surface_id':table.get('support_surface_id'),'status':'resolved','enabled':bool(module['enabled']),'center_xyz':centre,'canonical_center_z_m':centre[2],'expected_center_z_m':centre[2],'center_z_residual_m':0.,'row_axis_xyz':list(row),'downhill_axis_xyz':list(down),'normal_xyz':list(normal),'corners_3d':[list(p) for p in corners],'physical_width_m':table['physical_module_width_m'],'physical_height_m':table['physical_module_height_m'],'plane_width_m':w,'plane_height_m':h,'plan_projection_width_m':w,'plan_projection_height_m':h*math.cos(math.radians(table['tilt_deg'])),'plan_projection_corners_xy':[list(p[:2]) for p in corners],'orientation':table['module_orientation'],'azimuth_deg':table['azimuth_deg'],'tilt_deg':table['tilt_deg'],'mounting_height_m':None,'support_elevation_at_center_m':plane.elevation_at(centre[0],centre[1]) if plane else None,'minimum_support_clearance_m':min(clearances) if clearances else None,'maximum_support_clearance_m':max(clearances) if clearances else None,'row_index':module['row_index'],'column_index':module['column_index'],'table_index':module.get('table_index')}
    return geometry,corners,[]


def assert_generated_layout(field):
    if is_explicit(field):
        raise ValueError(f"PV field {field['pv_field_id']}: explicit tables are read-only; delete and recreate the field to change placement")


def assert_packable_field(scene, field):
    """Do not silently substitute footprints or ignore selected mesh obstacles."""
    assert_generated_layout(field)
    rules=field.get('exclusion_rules') or {}
    explicit=set(rules.get('obstacle_ids') or [])
    selected=sorted(o['obstacle_id'] for o in scene.get('obstacles',[]) if o.get('obstacle_type')=='imported_mesh' and (rules.get('use_scene_obstacles',True) or o['obstacle_id'] in explicit))
    if selected:
        raise ValueError(f"PV field {field.get('pv_field_id')}: generated packing cannot avoid mesh faces {selected}; use explicit tables or explicitly change obstacle selection")


def scene_has_explicit_layout(scene):
    return any(is_explicit(field) for field in scene.get('pv_fields',[]))
