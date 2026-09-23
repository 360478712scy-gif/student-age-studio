"""The same offline pinyin matching used by the UI, including polyphonic initials."""
from functools import lru_cache
import json
import logging
from pathlib import Path
import re
import unicodedata

def load_dictionary(path):
    # Search aids must not prevent opening the editor after an interrupted update.
    try:
        source=path.read_text(encoding='utf-8')
        value=json.loads(source.split('/* PINYIN_START */',1)[1].split('/* PINYIN_END */',1)[0])
        if not isinstance(value,dict) or any(
            not isinstance(k,str) or not isinstance(v,list) or not v
            or any(not isinstance(word,str) or not word for word in v)
            for k,v in value.items()
        ):
            raise ValueError('Invalid pinyin dictionary')
        return value
    except (OSError,UnicodeError,ValueError,IndexError) as exc:
        logging.getLogger(__name__).warning('Pinyin dictionary unavailable; literal search remains available: %s',exc)
        return {}

dictionary=load_dictionary(Path(__file__).with_name('search-pinyin.js'))

def normalize(value):
    text=unicodedata.normalize('NFKC',str(value or '')).casefold().replace('ü','v')
    return ''.join(c for c in unicodedata.normalize('NFD',text) if not '\u0300'<=c<='\u036f')

def compact(value):return re.sub(r"[\s_\-'’]+",'',value)

@lru_cache(maxsize=4096)
def prepare(text):
    tokens=[dictionary.get(c,[c]) for c in text]
    return tokens,''.join(v[0] for v in tokens),''.join(v[0][0] if v[0] else '' for v in tokens)

def alternatives(query,tokens,initials):
    active=set()
    for variants in tokens:
        following=set();active.add(0)
        for offset in active:
            for pronunciation in variants:
                part=pronunciation[0] if initials else pronunciation
                if not part:continue
                tail=query[offset:]
                if part.startswith(tail):return True
                if tail.startswith(part):following.add(offset+len(part))
        active=following
    return False

def matches(query,*values):
    query=normalize(query).strip()
    if not query:return True
    texts=[normalize(v) for v in values if v is not None]
    if any(query in text for text in texts):return True
    roman=compact(query)
    if not re.fullmatch('[a-z0-9]+',roman):return False
    for text in texts:
        tokens,full,initials=prepare(compact(text))
        if roman in full or roman in initials or alternatives(roman,tokens,False) or alternatives(roman,tokens,True):return True
    return False
