"""Bounded text buffers for generated catalogs; user Mod JSON keeps server.read_json."""
import json
from pathlib import Path
import threading

class _Reader:
    def __init__(self, stream):
        self.stream, self.buffer, self.pos, self.eof = stream, '', 0, False
        self.decoder = json.JSONDecoder(strict=False, parse_constant=self.invalid_constant)

    @staticmethod
    def invalid_constant(value):
        raise ValueError('Invalid JSON constant: ' + value)

    def fill(self):
        if self.eof:
            return False
        self.buffer = self.buffer[self.pos:]
        self.pos = 0
        block = self.stream.read(65536)
        self.buffer += block
        self.eof = not block
        return bool(block)

    def peek(self):
        while True:
            while self.pos < len(self.buffer) and self.buffer[self.pos] in ' \t\r\n':
                self.pos += 1
            if self.pos < len(self.buffer):
                return self.buffer[self.pos]
            if not self.fill():
                return ''

    def take(self, token):
        if self.peek() != token:
            raise ValueError('Expected ' + token + ' in generated catalog')
        self.pos += 1

    def value(self, depth=0):
        if depth > 256:
            raise ValueError('Generated catalog nesting too deep')
        char = self.peek()
        if not char:
            raise ValueError('Incomplete generated catalog')
        # Most rows fit in the current buffer: let the C JSON decoder parse them.
        try:
            value, end = self.decoder.raw_decode(self.buffer, self.pos)
            if self.eof or (end < len(self.buffer) and self.buffer[end] in ' \t\r\n,:]}'):
                self.pos = end
                return value
        except json.JSONDecodeError:
            pass
        if char in '{[':
            self.pos += 1
            result = {} if char == '{' else []
            close = '}' if char == '{' else ']'
            if self.peek() == close:
                self.pos += 1
                return result
            while True:
                if char == '{':
                    key = self.value(depth+1)
                    if not isinstance(key, str):
                        raise ValueError('Catalog object key must be a string')
                    self.take(':')
                    result[key] = self.value(depth+1)
                else:
                    result.append(self.value(depth+1))
                if self.peek() == close:
                    self.pos += 1
                    return result
                self.take(',')
        # A large string or a number split across buffers needs its complete token.
        while True:
            if not self.eof:
                self.fill()
            value, end = None, None
            try:
                value, end = self.decoder.raw_decode(self.buffer, self.pos)
            except json.JSONDecodeError:
                if self.eof:
                    raise
                continue
            if self.eof or (end < len(self.buffer) and self.buffer[end] in ' \t\r\n,:]}'):
                self.pos = end
                return value

def read_catalog(path):
    with Path(path).open('r', encoding='utf-8-sig') as stream:
        reader = _Reader(stream)
        result = reader.value()
        if reader.peek():
            raise ValueError('Trailing data in generated catalog')
        return result

class DeferredCatalog(dict):
    """Keep the existing dict contract, loading texture/audio indexes only on access."""
    def __init__(self, core, loaders, lock=None):
        super().__init__(core)
        self._loaders = loaders
        self._lock = lock or threading.RLock()

    def _ensure(self, key=None):
        with self._lock:
            for names, load in list(self._loaders):
                if key is not None and key not in names:
                    continue
                updates = load()  # failure leaves the loader available for retry
                for name, value in updates.items():
                    previous = dict.get(self, name)
                    if isinstance(previous, dict) and isinstance(value, dict):
                        value = {**previous, **value}
                    dict.__setitem__(self, name, value)
                self._loaders.remove((names, load))

    def __getitem__(self, key):
        self._ensure(key)
        return super().__getitem__(key)

    def get(self, key, default=None):
        self._ensure(key)
        return super().get(key, default)

    def __contains__(self, key):
        self._ensure(key)
        return super().__contains__(key)

    def keys(self):
        self._ensure()
        return super().keys()

    def items(self):
        self._ensure()
        return super().items()

    def values(self):
        self._ensure()
        return super().values()

    def __iter__(self):
        self._ensure()
        return super().__iter__()

    def copy(self):
        self._ensure()
        return dict(self)

    def __copy__(self):
        return self.copy()

    def __deepcopy__(self, memo):
        import copy
        self._ensure()
        result = {}
        memo[id(self)] = result
        for key, value in dict.items(self):
            result[copy.deepcopy(key, memo)] = copy.deepcopy(value, memo)
        return result
