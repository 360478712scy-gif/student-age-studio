"""Offline counterpart of search.js, using the same bundled pronunciations."""
import functools
import json
import re
import unicodedata
from pathlib import Path


@functools.lru_cache(maxsize=1)
def dictionary():
    source = Path(__file__).with_name('search-pinyin.js').read_text(encoding='utf-8')
    return json.JSONDecoder().raw_decode(source.split('/* PINYIN_START */', 1)[1].lstrip())[0]


def normalize(value):
    text = unicodedata.normalize('NFKC', str(value)).lower().replace('ü', 'v')
    return ''.join(c for c in unicodedata.normalize('NFD', text) if not '\u0300' <= c <= '\u036f')


def compact(value):
    return re.sub(r"[\s_\-'’]+", '', value)


def alternatives(query, tokens, initials):
    active = set()
    for variants in tokens:
        following = set()
        active.add(0)
        for offset in active:
            for pronunciation in variants:
                part = pronunciation[:1] if initials else pronunciation
                if not part:
                    continue
                tail = query[offset:]
                if part.startswith(tail):
                    return True
                if tail.startswith(part):
                    following.add(offset + len(part))
        active = following
    return False


def matches(query, *values):
    query = normalize(query).strip()
    if not query:
        return True
    texts = [normalize(v) for v in values if v is not None]
    if any(query in text for text in texts):
        return True
    roman = compact(query)
    if not re.fullmatch('[a-z0-9]+', roman):
        return False
    pronunciations = dictionary()
    for text in texts:
        tokens = [pronunciations.get(c, [c]) for c in compact(text)]
        if (roman in ''.join(v[0] for v in tokens)
                or roman in ''.join(v[0][:1] for v in tokens)
                or alternatives(roman, tokens, False) or alternatives(roman, tokens, True)):
            return True
    return False
