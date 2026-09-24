"""Native ShowSiteEvent uses 900 + map ID on entry and 800 + map ID on exit."""
def sync(events, maps, touched, native_maps, native_types, unreadable):
    candidates = {int(row.get('type', 0)) for row in events.values()
                  if isinstance(row, dict) and isinstance(row.get('type'), int)
                  and (800 < row['type'] < 900 or 900 < row['type'] < 1000)}
    if not candidates or 'EvtTypeCfg.json' in unreadable or 'MapCfg.json' in unreadable:
        return
    places = {**native_maps, **maps.get('MapCfg.json', {})}
    local = maps.get('EvtTypeCfg.json', {})
    for kind in sorted(candidates):
        key = str(kind)
        if key in local or key in native_types:
            continue
        place = places.get(str(kind - (900 if kind > 900 else 800)))
        if not isinstance(place, dict) or place.get('type') != 0:
            continue
        local[key] = {'id': kind, 'name': place.get('name') or '地点 ' + str(place['id']),
                      'type': [1], 'emptyIsTrue': 1}
        maps['EvtTypeCfg.json'] = local
        touched.add('EvtTypeCfg.json')
