"""Editor ownership survives disconnected runtime edges; never inferred by title."""
def ids(value):
    return [str(v) for v in value if type(v) is int or isinstance(v,str) and v.isdigit()] if isinstance(value,list) else []


def ownership(events, talks, options, folders, previous=None):
    event_ids=set(events)
    owners={t:set(ids(v)) & event_ids for t,v in (previous or {}).items() if t in talks}
    edges={t:ids(r.get('nextTalk'))+ids(r.get('nextTalk2'))+[
        dest for oid in ids(r.get('option')) for field in ('talkId','talkId2') for dest in ids(options.get(oid,{}).get(field))] for t,r in talks.items()}
    for folder in folders.values():
        parent=str(folder.get('parentTalkId'))
        edges.setdefault(parent,[]).extend(ids(folder.get('talkIds'))+[str(folder[k]) for k in ('routerId','exitId','endId') if folder.get(k)])
    retained={}
    for t,v in owners.items():
        for e in v: retained.setdefault(e,[]).append(t)
    def walk(todo, assign):
        seen=set()
        while todo:
            t=todo.pop()
            if t in seen or t not in talks:continue
            seen.add(t);assign(t);todo.extend(edges.get(t,[]))
    # Real connections decide first: a line reachable from an event's entry belongs to that event.
    reached={}
    for event,row in events.items():
        todo=ids(row.get('talkId'))+[dest for oid in ids(row.get('options')) for field in ('talkId','talkId2') for dest in ids(options.get(oid,{}).get(field))]
        walk(todo, lambda t,event=event: reached.setdefault(t,set()).add(event))
    # Remembered ownership only keeps disconnected (authored but not yet linked) lines with their event;
    # it never adds a second event to a line already reached from another event's entry.
    result={t:set(v) for t,v in reached.items()}
    for event in events:
        walk(list(retained.get(event,[])), lambda t,event=event: None if t in reached else result.setdefault(t,set()).add(event))
    return {t:sorted(map(int,v)) for t,v in result.items() if v}


def deletion(events,talks,options,folders,previous,removed,interactions=None,reference_talks=None):
    owners=ownership(events,talks,options,folders,previous)
    removed=set(map(str,removed))
    # Remove only dialogues owned by the explicitly removed events. A line still
    # owned by a surviving event (shared continuations, merged branches) stays.
    doomed={t for t in talks if (owned := set(map(str,owners.get(t,[])))) and owned <= removed}
    option_ids={o for e in removed for o in ids(events.get(e,{}).get('options'))}
    option_ids.update(o for t in doomed for o in ids(talks[t].get('option')))
    return doomed,option_ids


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
