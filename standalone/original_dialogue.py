"""Original TalkCfg/OptionCfg bodies, kept out of game-catalog.json and read by id.

The catalog only lists ``baseTalkIds`` so that opening a mod never parses the whole
original dialogue. This store keeps every original talk/option row in a small SQLite
file next to the catalog; the editor pulls in just the rows an event actually reaches
(original events a mod overrides, events opened in original-resource mode), so those
events show their dialogue and can be edited as overrides.
"""
import json
import os
import sqlite3
import tempfile
import time
from pathlib import Path

from platform_support import replace_file
from storage_paths import game_cache

FILENAME = 'original-dialogue-v1.sqlite'
TABLES = {'TalkCfg': 'talks', 'OptionCfg': 'options'}
MAX_ROWS = 20000  # one load never pulls more original rows than this
# A read-only handle still locks the file on Windows. Reopen after this long
# without use so catalog refreshes can replace it; reopening is transparent.
IDLE_CLOSE_SECONDS = 120


def path(game):
    return Path(game_cache(game)) / FILENAME


def write(game, talks, options):
    """Atomically (re)write the store. Rows are plain JSON objects keyed by id string."""
    target = path(game)
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix='.original-dialogue-', suffix='.sqlite', dir=str(target.parent))
    os.close(handle)
    try:
        connection = sqlite3.connect(temporary)
        try:
            connection.execute('PRAGMA journal_mode=OFF')
            for table in TABLES.values():
                connection.execute(f'CREATE TABLE {table} (id TEXT PRIMARY KEY, body TEXT NOT NULL)')
            connection.executemany('INSERT OR REPLACE INTO talks VALUES (?, ?)',
                                   ((str(k), json.dumps(v, ensure_ascii=False, separators=(',', ':'))) for k, v in talks.items() if isinstance(v, dict)))
            connection.executemany('INSERT OR REPLACE INTO options VALUES (?, ?)',
                                   ((str(k), json.dumps(v, ensure_ascii=False, separators=(',', ':'))) for k, v in options.items() if isinstance(v, dict)))
            connection.commit()
        finally:
            connection.close()
        # Tolerate a reader holding the file on Windows; replace_file retries
        # sharing violations before giving up.
        replace_file(temporary, target)
    except BaseException:
        try: os.unlink(temporary)
        except OSError: pass
        raise
    return target


def _ids(value):
    if isinstance(value, list):
        return [int(v) for v in value if isinstance(v, (int, float)) and not isinstance(v, bool) and float(v).is_integer() and v > 0]
    if isinstance(value, (int, float)) and not isinstance(value, bool) and float(value).is_integer() and value > 0:
        return [int(value)]
    return []


def talk_links(row):
    """Talks and options one dialogue line points at."""
    talks = _ids(row.get('nextTalk')) + _ids(row.get('nextTalk2'))
    return talks, _ids(row.get('option'))


def option_links(row):
    return _ids(row.get('talkId')) + _ids(row.get('talkId2'))


class OriginalDialogue:
    """Lazy, read-only access; reopens when the file changes or the game moves."""

    def __init__(self, game_getter):
        self._game = game_getter
        self._connection = None
        self._stamp = None
        self._last_use = 0.0

    def _open(self):
        try:
            target = path(self._game())
            stamp = (str(target), target.stat().st_mtime_ns, target.stat().st_size)
        except (OSError, TypeError, ValueError):
            self.close()
            return None
        if self._connection is not None and stamp == self._stamp:
            if time.monotonic() - self._last_use < IDLE_CLOSE_SECONDS:
                self._last_use = time.monotonic()
                return self._connection
            # Idle too long: drop the handle so a pending catalog refresh can
            # replace the file on Windows, then reopen transparently below.
            self.close()
        self.close()
        uri = 'file:' + str(target).replace('?', '%3F').replace('#', '%23') + '?mode=ro'
        try:
            self._connection = sqlite3.connect(uri, uri=True, check_same_thread=False)
            self._connection.execute('SELECT 1 FROM talks LIMIT 1')
            self._connection.execute('SELECT 1 FROM options LIMIT 1')
        except sqlite3.Error:
            self.close()
            return None
        self._stamp = stamp
        self._last_use = time.monotonic()
        return self._connection

    def close(self):
        if self._connection is not None:
            try: self._connection.close()
            except sqlite3.Error: pass
        self._connection, self._stamp = None, None

    def available(self):
        return self._open() is not None

    def rows(self, table, ids):
        """Rows for the given ids (missing ids are simply absent)."""
        connection = self._open()
        name = TABLES.get(table)
        keys = [str(i) for i in dict.fromkeys(ids) if str(i).isdigit()]
        if connection is None or not name or not keys:
            return {}
        result = {}
        for start in range(0, len(keys), 500):
            chunk = keys[start:start + 500]
            query = f'SELECT id, body FROM {name} WHERE id IN ({",".join("?" * len(chunk))})'
            try:
                for key, body in connection.execute(query, chunk):
                    try:
                        row = json.loads(body)
                    except ValueError:
                        continue
                    if isinstance(row, dict):
                        result[key] = row
            except sqlite3.Error:
                self.close()
                return result
        return result

    def reachable(self, talk_seeds, option_seeds, local_talks, local_options, limit=MAX_ROWS):
        """Original rows reachable from the seeds without stepping onto local overrides.

        Local rows win: an id present in ``local_talks``/``local_options`` is never fetched
        (the caller already knows its links), and traversal stops there.
        """
        talks, options = {}, {}
        pending_talks = [str(i) for i in dict.fromkeys(talk_seeds) if str(i) not in local_talks]
        pending_options = [str(i) for i in dict.fromkeys(option_seeds) if str(i) not in local_options]
        seen_talks, seen_options = set(pending_talks), set(pending_options)
        while (pending_talks or pending_options) and len(talks) + len(options) < limit:
            found_talks = self.rows('TalkCfg', pending_talks) if pending_talks else {}
            found_options = self.rows('OptionCfg', pending_options) if pending_options else {}
            pending_talks, pending_options = [], []
            for key, row in found_talks.items():
                talks[key] = row
                next_talks, next_options = talk_links(row)
                for ident in next_talks:
                    k = str(ident)
                    if k not in seen_talks and k not in local_talks:
                        seen_talks.add(k); pending_talks.append(k)
                for ident in next_options:
                    k = str(ident)
                    if k not in seen_options and k not in local_options:
                        seen_options.add(k); pending_options.append(k)
            for key, row in found_options.items():
                options[key] = row
                for ident in option_links(row):
                    k = str(ident)
                    if k not in seen_talks and k not in local_talks:
                        seen_talks.add(k); pending_talks.append(k)
        return talks, options


def story_seeds(events, talks, options, local_talks, local_options):
    """Seeds for a story document: event entries plus links leaving local rows."""
    talk_seeds, option_seeds = [], []
    for row in events.values():
        if isinstance(row, dict):
            talk_seeds += _ids(row.get('talkId'))
            option_seeds += _ids(row.get('options'))
    for key in local_talks:
        row = talks.get(key)
        if isinstance(row, dict):
            next_talks, next_options = talk_links(row)
            talk_seeds += next_talks; option_seeds += next_options
    for key in local_options:
        row = options.get(key)
        if isinstance(row, dict):
            talk_seeds += option_links(row)
    return talk_seeds, option_seeds
