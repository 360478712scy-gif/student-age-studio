"""Mod-scoped runtime extension settings; never pretend these are native Cfg fields."""
import copy,math

def validate(value,people,removed,old,api):
    if not isinstance(value,dict):raise api.ApiError('恋爱配置必须为人物配置。')
    out=copy.deepcopy(value)
    for key in list(out):
        if key in removed:del out[key];continue
        row=out[key]
        if key not in people and key not in old:raise api.ApiError('恋爱配置必须关联模组人物。')
        if not isinstance(row,dict):raise api.ApiError('人物恋爱配置无效。')
        if row==old.get(key):continue
        for name in ('enabled','male','female'):
            if type(row.get(name)) is not bool:raise api.ApiError('请选择是否恋爱及适配主角。')
        if row['enabled'] and not (row['male'] or row['female']):raise api.ApiError('可恋爱时请至少选择一种适配主角。')
        for name,lo,hi,integer in [('minGrade',7,12,True),('minRelation',4,5,True),('minFavor',0,100000,False),('favorWeight',0,1,False),('attrWeight',0,1,False)]:
            v=row.get(name)
            if type(v) not in (int,float) or not math.isfinite(v) or not lo<=v<=hi or integer and int(v)!=v:raise api.ApiError('恋爱条件数值无效：'+name)
        conditions=row.get('conditions',[])
        if not isinstance(conditions,list) or any(not isinstance(c,list) or len(c)<2 or any(type(v) not in (int,float) or not math.isfinite(v) for v in c) for c in conditions):raise api.ApiError('表白前提必须为有效的条件列表。')
        out[key]={**old.get(key,{}),**row}
    return out
