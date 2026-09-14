"""Write an explicitly ordered dialogue folder as a native nextTalk chain."""
def compile_sequences(store, groups, previous, all_maps, touched, api):
    talks = all_maps.setdefault('TalkCfg.json', {})
    for folder in groups.values():
        if not folder.get('sequence'): continue
        ids = folder['talkIds']
        for index, ident in enumerate(ids):
            following = [ids[index + 1]] if index + 1 < len(ids) else []
            if talks[str(ident)].get('nextTalk') != following:
                talks[str(ident)]['nextTalk'] = following
                touched.add('TalkCfg.json')
        for use in folder.get('uses', []):
            if ids: use['entryId'] = ids[0]
