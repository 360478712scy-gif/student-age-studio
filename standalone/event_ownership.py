"""Editor ownership survives disconnected runtime edges; never inferred by title."""
def ids(value):
    return [str(v) for v in value if type(v) is int or isinstance(v,str) and v.isdigit()] if isinstance(value,list) else []


def _number(value):
    return int(value) if isinstance(value,str) and value.isdigit() else None


def _links(talks, options, folders):
    edges={t:ids(r.get('nextTalk'))+ids(r.get('nextTalk2'))+[
        dest for oid in ids(r.get('option')) for field in ('talkId','talkId2') for dest in ids(options.get(oid,{}).get(field))] for t,r in talks.items()}
    for folder in folders.values():
        parent=str(folder.get('parentTalkId'))
        edges.setdefault(parent,[]).extend(ids(folder.get('talkIds'))+[str(folder[k]) for k in ('routerId','exitId','endId') if folder.get(k)])
    reverse={}
    for src,dests in edges.items():
        for dest in dests: reverse.setdefault(dest,[]).append(src)
    return edges, reverse


def _walk(talks, edges, todo, assign, allow=None):
    seen=set()
    while todo:
        t=todo.pop()
        if t in seen or t not in talks:continue
        seen.add(t)
        if allow is not None and not allow(t):continue
        assign(t);todo.extend(edges.get(t,[]))


def _forward(events, talks, options, edges):
    """Lines reached by walking forward from an event entry. This is real membership."""
    reached={}
    for event,row in events.items():
        todo=ids(row.get('talkId'))+[dest for oid in ids(row.get('options')) for field in ('talkId','talkId2') for dest in ids(options.get(oid,{}).get(field))]
        _walk(talks, edges, todo, lambda t,event=event: reached.setdefault(t,set()).add(event))
    return reached


def display_ownership(events, talks, options, folders, band=None, _prepared=None):
    """Lines to show while an event is open. This does not make them members of the event.

    A line that runs into the event, continues out of it, or sits in the event's number
    block (talk = event×1000+n, option = event×100+n) is listed with that event. It stays
    an external dialogue unless the event entry actually reaches it.
    ``band`` limits the number block to those event ids.
    """
    event_ids=set(events)
    band_ids=event_ids if band is None else {str(v) for v in band if str(v) in event_ids}
    # ownership() already has the links and forward walk; reuse them (the walk is copied, it is extended here).
    edges, reverse, forward_walk=_prepared if _prepared else (*_links(talks, options, folders), None)
    reached={t:set(v) for t,v in forward_walk.items()} if forward_walk is not None else _forward(events, talks, options, edges)
    forward=set(reached)
    by_event={}
    for talk,evs in reached.items():
        for event in evs: by_event.setdefault(event,set()).add(talk)
    for event,members in by_event.items():
        todo,seen=list(members),set(members)
        fresh=[]
        while todo:
            current=todo.pop()
            for prev in reverse.get(current,[]):
                if prev in forward or prev in seen or prev not in talks:continue
                seen.add(prev);reached.setdefault(prev,set()).add(event);todo.append(prev);fresh.append(prev)
        _walk(talks, edges, fresh, lambda t,event=event: reached.setdefault(t,set()).add(event),
              lambda t,event=event: not (t in forward and event not in reached.get(t,())))
    # Bucket talks and options by their event-number prefix once; scanning every talk for each
    # event is quadratic and took seconds on large mods.
    talks_by_event,options_by_event={},{}
    for t in talks:
        if (n:=_number(t)) is not None: talks_by_event.setdefault(n//1000,[]).append(t)
    for oid,row in options.items():
        if (n:=_number(oid)) is not None: options_by_event.setdefault(n//100,[]).append(row)
    for event in band_ids:
        number=_number(event)
        if not number:continue
        seeds=list(talks_by_event.get(number,()))
        for row in options_by_event.get(number,()):
            seeds.extend(ids(row.get('talkId'))+ids(row.get('talkId2')))
        def allow(t,event=event):
            owned=reached.get(t)
            if owned and event not in owned and t in forward:
                owned.add(event)
                return False
            return True
        _walk(talks, edges, seeds, lambda t,event=event: reached.setdefault(t,set()).add(event), allow)
    return {t:sorted(map(int,v)) for t,v in reached.items() if v}


def ownership(events, talks, options, folders, previous=None, band=None, anchor=None):
    """Real membership: the event entry's own forward chain, plus lines authored into the event.

    Lines that are only shown beside an event (a chain that runs into it, or a matching
    number with no link from the entry) stay out of this map, so the external-dialogue
    list keeps them. ``anchor`` ids were just created inside the event and stay members
    even when their number would otherwise only be a display hint.
    """
    event_ids=set(events)
    anchored={str(v) for v in (anchor or []) if str(v) in talks}
    edges,reverse=_links(talks, options, folders)
    forward=_forward(events, talks, options, edges)
    # A saved owner that exists only because an older build treated display lines as
    # members is dropped, otherwise the external list stays empty after one save.
    shown=set(display_ownership(events, talks, options, folders, band, _prepared=(edges, reverse, forward)))
    extra=shown-set(forward)-anchored
    retained={}
    for t,v in (previous or {}).items():
        if t not in talks or t in extra:continue
        for e in set(ids(v)) & event_ids: retained.setdefault(e,[]).append(t)
    result={t:set(v) for t,v in forward.items()}
    for event in events:
        _walk(talks, edges, list(retained.get(event,[])), lambda t,event=event: None if t in forward else result.setdefault(t,set()).add(event))
    for t in anchored:
        if t not in result: result[t]=set()
        for e in set(ids((previous or {}).get(t))) & event_ids: result[t].add(e)
    return {t:sorted(map(int,v)) for t,v in result.items() if v}


def deletion(events,talks,options,folders,previous,removed,interactions=None,reference_talks=None,band=None):
    owners=ownership(events,talks,options,folders,previous,band)
    removed=set(map(str,removed))
    # Remove only dialogues owned by the explicitly removed events. A line still
    # owned by a surviving event (shared continuations, merged branches) stays.
    doomed={t for t in talks if (owned := set(map(str,owners.get(t,[])))) and owned <= removed}
    option_ids={o for e in removed for o in ids(events.get(e,{}).get('options'))}
    option_ids.update(o for t in doomed for o in ids(talks[t].get('option')))
    kept_options={o for e,row in events.items() if e not in removed for o in ids(row.get('options'))}
    kept_options.update(o for t,row in talks.items() if t not in doomed for o in ids(row.get('option')))
    return doomed,option_ids-kept_options


def interaction_talks(interactions,talks,options=None):
    """Reachability from native idle chats, separate from event ownership."""
    pending=[str(r.get('talkId')) for r in interactions.values() if isinstance(r,dict) and r.get('talkId')]
    found=set();options=options or {}
    while pending:
        key=pending.pop()
        if key in found or key not in talks:continue
        found.add(key);row=talks[key]
        pending+=ids(row.get('nextTalk'))+ids(row.get('nextTalk2'))
        for oid in ids(row.get('option')):
            pending+=ids(options.get(oid,{}).get('talkId'))+ids(options.get(oid,{}).get('talkId2'))
    return found
