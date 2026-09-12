"""Native numeric arrays and repairs for historical Studio character writes."""
import copy
import math
import re

PERSONALITY_IDS = (101,102,103,104,105,106,109,110)

def valid_value(value, kind):
    kind = kind.lower().replace('system.', '').replace(' ', '')
    if kind.startswith('list<') or kind.endswith('[]'):
        child = kind[5:-1] if kind.startswith('list<') else kind[:-2]
        return isinstance(value, list) and all(valid_value(v,child) for v in value)
    if kind in ('int','int32','integer','long','int64'):
        bound = 2**63 if kind in ('long','int64') else 2**31
        return type(value) is int and -bound <= value < bound
    if kind in ('float','single','double','decimal','number'):
        return type(value) in (int,float) and math.isfinite(value)
    if kind == 'string': return isinstance(value,str)
    if kind in ('bool','boolean'): return type(value) is bool
    return True

def class_number(value):
    if value is None or isinstance(value,str) and not value.strip(): return 0
    if not isinstance(value,str): return value
    text=value.strip()
    if re.fullmatch(r'[+-]?\d+',text): return int(text)
    match=re.fullmatch(r'(?:(?:小学|初中|高中)|[小初高][一二三四五六1-6]|[一二三四五六七八九十]+年级)?([一二三四五六七八九两十]+|\d+)班',text)
    if not match:return value
    label=match[1];digits={c:i for i,c in enumerate('零一二三四五六七八九')};digits['两']=2
    if label.isdigit():return int(label)
    if label in digits:return digits[label]
    if re.fullmatch('[一二三四五六七八九两]?十[一二三四五六七八九]?',label):
        tens,units=label.split('十');return digits.get(tens,1)*10+digits.get(units,0)
    return value

def normalize_growth(row):
    row = copy.deepcopy(row)
    classes = row.get('className')
    if isinstance(classes,list):
        # Preserve unknown class labels for an actionable validation error.
        row['className'] = [class_number(v) for v in classes]
    values = row.get('personalitys')
    if isinstance(values,list) and values and all(isinstance(v,list) and len(v)==2 and type(v[0]) is int and v[0] in PERSONALITY_IDS for v in values):
        mapped = dict(values)
        if len(mapped)==len(values): row['personalitys'] = [mapped.get(i,0) for i in PERSONALITY_IDS]
    values = row.get('personalitys')
    if isinstance(values,list) and values and valid_value(values,'list<float>') and len(values)<8:
        row['personalitys'] = values+[0]*(8-len(values))
    return row

def default_growth(store, ident):
    result = {f['name']:copy.deepcopy(f.get('default')) for f in store.table_schema('PersonGrowCfg').get('fields',[])}
    result.update(id=int(ident),order=0,attr=[0,0,0],grow=[],className=[],personalitys=[])
    return result
