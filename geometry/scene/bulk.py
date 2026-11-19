"""Ordered MESH1 geometry mutations, isolated by the editor's one undo frame."""
from __future__ import annotations
from copy import deepcopy

MAX_GEOMETRY_BYTES=16*1024*1024


class GeometryBatchError(ValueError):
    def __init__(self,message,*,code='geometry_invalid',operation_index=None,operation_id=None,object_id=None,findings=None):
        super().__init__(message)
        self.detail={'code':code,'message':message,'operation_index':operation_index,'operation_id':operation_id,'object_id':object_id,'findings':findings or []}


def validate_batch_limits(operations):
    if not isinstance(operations,list) or not 1<=len(operations)<=2048:
        raise GeometryBatchError('operations must contain 1 to 2048 entries')
    counters={'tables':0,'meshes':0,'vertices':0,'faces':0,'indices':0,'modules':0};seen=set()
    for index,op in enumerate(operations):
        oid=op.get('operation_id') if isinstance(op,dict) else None
        try:
            if not isinstance(oid,str) or not oid.strip() or oid in seen:raise ValueError('operation_id must be a unique nonblank string')
            seen.add(oid)
            if op.get('operation_type') in {'create_mesh','replace_mesh'}:
                counters['meshes']+=1;mesh=op.get('mesh')
                if not isinstance(mesh,dict):raise ValueError('mesh must be an object')
                vertices,faces=mesh.get('vertices_m'),mesh.get('faces')
                if not isinstance(vertices,list) or not isinstance(faces,list):raise ValueError('mesh requires vertices_m and faces arrays')
                counters['vertices']+=len(vertices);counters['faces']+=len(faces)
                for face in faces:
                    if not isinstance(face,list) or not 3<=len(face)<=512:raise ValueError('each face must contain 3 to 512 indices')
                    counters['indices']+=len(face)
            if op.get('operation_type')=='create_explicit_field':
                tables=op.get('tables')
                if not isinstance(tables,list):raise ValueError('tables must be an array')
                counters['tables']+=len(tables)
                for table in tables:
                    if not isinstance(table,dict):raise ValueError('table must be an object')
                    a,b=table.get('modules_across'),table.get('modules_up')
                    if type(a) is not int or type(b) is not int or min(a,b)<1:raise ValueError('table module counts must be positive integers')
                    counters['modules']+=a*b
            for key,limit in {'tables':2000,'meshes':512,'vertices':50000,'faces':50000,'indices':500000,'modules':50000}.items():
                if counters[key]>limit:raise ValueError(f'batch {key} count exceeds {limit}')
        except (ValueError,TypeError,KeyError,OverflowError) as exc:
            raise GeometryBatchError(str(exc),operation_index=index,operation_id=oid,object_id=(op.get('obstacle_id') or op.get('pv_field_id')) if isinstance(op,dict) else None) from exc
    return counters


def apply_geometry_operations(scene,operations,definitions):
    from geometry.scene.mesh import make_mesh_obstacle
    from geometry.pvfield.explicit import create_explicit_field,is_explicit
    validate_batch_limits(operations);effects=[]
    def unique(*ids):
        current=set()
        for collection,key in (('surfaces','surface_id'),('obstacles','obstacle_id'),('reference_lines','reference_line_id'),('pv_fields','pv_field_id'),('module_instances','module_instance_id')):
            for obj in scene.get(collection,[]):current.add(obj[key]);current.add(obj.get('scene_object_id'))
        if any(not isinstance(i,str) or not i.strip() for i in ids) or len(ids)!=len(set(ids)) or any(i in current for i in ids):raise ValueError(f'duplicate, ambiguous or invalid object identity: {ids}')
    for index,op in enumerate(operations):
        kind=op.get('operation_type');object_id=op.get('obstacle_id') or op.get('pv_field_id')
        try:
            common={'operation_id','operation_type'}
            allowed={'create_mesh':{'obstacle_id','scene_object_id','name','mesh','provenance','shading_enabled'},'replace_mesh':{'obstacle_id','name','mesh','provenance','shading_enabled'},'delete_mesh':{'obstacle_id'},'create_explicit_field':{'pv_field_id','name','tables','provenance'},'delete_explicit_field':{'pv_field_id'}}
            if kind not in allowed:raise ValueError(f'operation_type {kind!r} is not supported')
            if set(op)-common-allowed[kind]:raise ValueError('unknown operation parameters')
            if not isinstance(object_id,str) or not object_id.strip():raise ValueError('object identity must be a nonblank string')
            removed=[];added=[]
            if kind in {'create_mesh','replace_mesh'}:
                old=next((o for o in scene['obstacles'] if o['obstacle_id']==object_id),None)
                if kind=='create_mesh':
                    unique(object_id,op['scene_object_id']);scene_object_id=op['scene_object_id']
                else:
                    if old is None or old.get('obstacle_type')!='imported_mesh':raise ValueError(f'mesh {object_id} not found')
                    if old.get('locked',False):raise ValueError(f'mesh {object_id} is locked')
                    scene_object_id=old['scene_object_id']
                obstacle=make_mesh_obstacle(obstacle_id=object_id,scene_object_id=scene_object_id,name=op.get('name',old['name'] if old else None),mesh=op['mesh'],provenance=op.get('provenance',old['provenance'] if old else None),shading_enabled=op.get('shading_enabled',old.get('shading_enabled',True) if old else True))
                if old is None:scene['obstacles'].append(obstacle)
                else:
                    for key in ('visible','locked','selectable'):obstacle[key]=old.get(key,obstacle[key])
                    scene['obstacles'][scene['obstacles'].index(old)]=obstacle
            elif kind=='delete_mesh':
                old=next((o for o in scene['obstacles'] if o['obstacle_id']==object_id),None)
                if old is None or old.get('obstacle_type')!='imported_mesh':raise ValueError(f'mesh {object_id} not found')
                if old.get('locked',False):raise ValueError(f'mesh {object_id} is locked')
                scene['obstacles'].remove(old)
            elif kind=='create_explicit_field':
                unique(object_id)
                field,added=create_explicit_field(scene,definitions,pv_field_id=object_id,name=op['name'],tables=op['tables'],provenance=op['provenance'])
                unique(object_id,*(module['module_instance_id'] for module in added))
                scene['pv_fields'].append(field);scene['module_instances'].extend(added)
            else:
                field=next((f for f in scene['pv_fields'] if f['pv_field_id']==object_id),None)
                if field is None or not is_explicit(field):raise ValueError(f'explicit field {object_id} not found')
                removed=[m for m in scene['module_instances'] if m['pv_field_id']==object_id]
                if field.get('locked',False) or any(m.get('locked',False) for m in removed):raise ValueError(f'explicit field {object_id} or its modules are locked')
                scene['pv_fields'].remove(field);scene['module_instances']=[m for m in scene['module_instances'] if m['pv_field_id']!=object_id]
            effects.append({'operation_index':index,'operation_id':op['operation_id'],'operation_type':kind,'object_id':object_id,'added_module_ids':[m['module_instance_id'] for m in added],'removed_module_ids':[m['module_instance_id'] for m in removed],'table_count':len(op.get('tables',[]))})
        except (ValueError,KeyError,TypeError,AttributeError,IndexError,OverflowError) as exc:
            raise GeometryBatchError(f'Operation {index} ({op["operation_id"]}), object {object_id}: {exc}',operation_index=index,operation_id=op['operation_id'],object_id=object_id) from exc
    return effects
