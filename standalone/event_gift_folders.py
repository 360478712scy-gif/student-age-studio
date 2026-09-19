"""Expose event-owned GiftEvtCfg entries in the shared external dialogue editor.

Only editor metadata is synthesized. Native entries remain the single source of
truth; no duplicate gift rules or synthetic sequential dialogue chains are made.
"""
import copy


def sync(state, maps, touched, *, external_edit=False, previous=None):
    if 'GiftEvtCfg.json' not in maps:
        return
    events, gifts, talks = (maps.get(n+'.json', {}) for n in ('EvtCfg', 'GiftEvtCfg', 'TalkCfg'))
    groups = state.get('externalDialogueFolders', {})
    if not groups and not any(e.get('studioGiftBindings') for e in events.values()):
        return
    state['externalDialogueFolders'] = groups
    for folder in groups.values():
        owner = events.get(str(folder.get('giftEventId')))
        if folder.get('giftEventId') and (not owner or not owner.get('studioGiftBindings')):
            folder['uses'] = [u for u in folder.get('uses', []) if not u.get('eventGiftBinding')]
            folder.pop('giftEventId', None)
    if external_edit:
        for fid, old in (previous or {}).items():
            if fid not in groups and old.get('giftEventId'):
                event=events.get(str(old['giftEventId']))
                if event and event.get('studioGiftBindings'):
                    event['studioGiftBindings']=[]; touched.add('EvtCfg.json')
        # The external editor may change the entry/recipient/item. Carry that
        # change back to the owning event before the next event editor save.
        for folder in groups.values():
            event = events.get(str(folder.get('giftEventId')))
            if not event:
                continue
            uses = [u for u in folder.get('uses', []) if u.get('kind') == 'gift']
            bindings = []
            roots = None
            for use in uses:
                row = gifts.get(str(use.get('recordId')), {})
                npc = use.get('npc')
                if npc not in (row.get('npc') or []):
                    continue
                slot = row['npc'].index(npc)
                if roots is None:
                    roots = copy.deepcopy(row['talkId'][slot])
                binding = dict(id=row['id'], index=slot, npc=npc)
                if binding not in bindings:
                    bindings.append(binding)
            before = copy.deepcopy(event)
            event['studioGiftBindings'] = bindings
            if roots is not None:
                event['talkId'] = roots
                cond = gifts[str(bindings[0]['id'])].get('cond', [])
                # Count/rate are managed separately by the event editor.
                count=event.get('maxcount',0);count=count if isinstance(count,(int,float)) else 0
                probability=event.get('rate',1);probability=probability if isinstance(probability,(int,float)) else 1
                counter = [111, -1, event['id'], event.get('studioGiftCounterSlot'), max(0,count)-1]
                rate = [0, 1, probability if probability>0 else -1] if probability<1 else None
                event['condition'] = [copy.deepcopy(c) for c in cond if c != counter and c != rate]
            if event != before:
                touched.add('EvtCfg.json')
    for event in events.values():
        bindings = event.get('studioGiftBindings') or []
        if not bindings:
            continue
        existing = next((key for key, f in groups.items() if f.get('giftEventId') == event['id']), None)
        roots = [i for i in event.get('talkId', []) if str(i) in talks]
        if not roots:
            continue
        seen, pending, ids = set(), list(reversed(roots)), []
        while pending:
            ident = pending.pop()
            if ident in seen or str(ident) not in talks:
                continue
            seen.add(ident); ids.append(ident)
            row = talks[str(ident)]
            following = list(row.get('nextTalk') or []) + list(row.get('nextTalk2') or [])
            for oid in row.get('option') or []:
                option = maps.get('OptionCfg.json', {}).get(str(oid), {})
                following += list(option.get('talkId') or []) + list(option.get('talkId2') or [])
            pending.extend(reversed([i for i in following if i>0]))
        # Respect an existing user folder containing the same event dialogue.
        if existing is None:
            existing = next((key for key, f in groups.items() if set(roots) & set(f.get('talkIds', [])) and not f.get('giftEventId')), None)
        key = existing or 'gift-event-' + str(event['id'])
        folder = groups.get(key, {'name': (event.get('title') or '送礼对话')[:110], 'talkIds': []})
        occupied = {i for k, f in groups.items() if k != key for i in f.get('talkIds', [])}
        folder['talkIds'] = list(dict.fromkeys([i for i in folder.get('talkIds', []) if str(i) in talks] + [i for i in ids if i not in occupied]))
        folder['giftEventId'] = event['id']
        folder['sequence'] = False
        uses = [u for u in folder.get('uses', []) if not u.get('eventGiftBinding')]
        for binding in bindings:
            row = gifts.get(str(binding.get('id')), {})
            slot = binding.get('index', -1)
            if not isinstance(slot, int) or slot < 0 or slot >= len(row.get('talkId') or []):
                continue
            native = row['talkId'][slot]
            for gender, index in ([('both', None)] if len(native) == 1 else [('male', 0), ('female', 1)]):
                if not native or index is not None and index >= len(native):
                    continue
                entry = native[0 if index is None else index]
                if entry not in folder['talkIds']:
                    continue
                path = ['talkId', slot] + ([] if index is None else [index])
                written = [entry] if index is None else entry
                params = {k: copy.deepcopy(row[k]) for k in ('cond', 'redpoint') if k in row}
                modes = row.get('type') or []
                uses.append(dict(id=f"event-gift-{row['id']}-{slot}-{gender}", kind='gift', eventGiftBinding=True,
                                 npc=row['npc'][slot], item=row['item'], recordId=row['id'], entryId=entry,
                                 gender=gender, giftMode=modes[slot] if slot<len(modes) else 0,
                                 params=params, baseParams=copy.deepcopy(params),
                                 _target=dict(recordId=row['id'], path=path, previous=copy.deepcopy(written), written=written)))
        folder['uses'] = uses
        groups[key] = folder
