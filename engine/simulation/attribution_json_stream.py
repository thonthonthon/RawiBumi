"""Bounded v1 attribution decoding with operation-owned temporary storage.

Only the outer record, payload object, and intervals array are interpreted here.
Other values are framed incrementally and decoded by the standard JSON parser.
Duplicate keys are rejected: a streamed intervals member cannot be overwritten.
"""
from contextlib import contextmanager
import json
from pathlib import Path

import pandas as pd

from .artifacts import ElectricalIntervalStore
from .detailed_attribution import DetailedDCAttributionResult


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate attribution JSON key")
        result[key] = value
    return result


class _Reader:
    def __init__(self, stream, read_size):
        self.stream, self.read_size = stream, read_size
        self.buffer, self.position = "", 0

    def peek(self):
        if self.position == len(self.buffer):
            self.buffer = self.stream.read(self.read_size)
            self.position = 0
        return self.buffer[self.position:self.position + 1]

    def take(self):
        char = self.peek()
        if not char:
            raise ValueError("truncated attribution JSON")
        self.position += 1
        return char

    def whitespace(self):
        while self.peek() and self.peek() in " \t\r\n":
            self.take()

    def expect(self, char):
        self.whitespace()
        if self.take() != char:
            raise ValueError("malformed attribution JSON structure")

    def value(self):
        self.whitespace()
        first = self.peek()
        if not first:
            raise ValueError("truncated attribution JSON")
        parts, stack = [], []
        quoted, escaped = False, False
        # Framing is linear even for large intervals; json.loads checks syntax,
        # escapes, number grammar, and nested object/array grammar afterwards.
        if first in '{["':
            while True:
                char = self.take()
                parts.append(char)
                if quoted:
                    if escaped:
                        escaped = False
                    elif char == '\\':
                        escaped = True
                    elif char == '"':
                        quoted = False
                        if not stack:
                            break
                elif char == '"':
                    quoted = True
                elif char in '{[':
                    stack.append('}' if char == '{' else ']')
                elif char in '}]':
                    if not stack or stack.pop() != char:
                        raise ValueError("malformed attribution JSON nesting")
                    if not stack:
                        break
        else:
            while self.peek() and self.peek() not in ' \t\r\n,]}':
                parts.append(self.take())
        return json.loads(''.join(parts), object_pairs_hook=_unique)

    def object(self, member):
        self.expect('{')
        result = {}
        self.whitespace()
        if self.peek() == '}':
            self.take()
            return result
        while True:
            self.whitespace()
            if self.peek() != '"':
                raise ValueError("attribution JSON object key must be a string")
            key = self.value()
            if key in result:
                raise ValueError("duplicate attribution JSON key")
            self.expect(':')
            result[key] = member(key)
            self.whitespace()
            char = self.take()
            if char == '}':
                return result
            if char != ',':
                raise ValueError("malformed attribution JSON object")

    def intervals(self, store):
        self.expect('[')
        self.whitespace()
        previous = None
        if self.peek() == ']':
            self.take()
            return store
        while True:
            row = self.value()
            if not isinstance(row, dict):
                raise ValueError("attribution interval must be an object")
            start, end, evaluation = (pd.Timestamp(row[k]) for k in
                                     ('interval_start', 'interval_end', 'evaluation_time'))
            if start.tzinfo is None or end.tzinfo is None or evaluation.tzinfo is None:
                raise ValueError("attribution interval timestamp must be timezone-aware")
            if not start < end or (end-start).total_seconds() != row['duration_seconds'] or (previous is not None and start != previous):
                raise ValueError("attribution interval alignment mismatch")
            previous = end
            store.append(row)
            del row
            self.whitespace()
            char = self.take()
            if char == ']':
                return store
            if char != ',':
                raise ValueError("malformed attribution intervals array")


@contextmanager
def open_persisted_attribution(path, *, chunk_size=128, _read_size=65536):
    """Yield (validated source, logical payload); neither escapes this lifetime.

    Chunk and read sizes are transport settings and never scientific inputs.
    TextIOWrapper strictly decodes UTF-8 across byte boundaries. The temporary
    interval store is closed even if decoding, validation, or the consumer fails.
    """
    if isinstance(_read_size, bool) or not isinstance(_read_size, int) or _read_size < 1:
        raise ValueError("read size must be a positive integer")
    store = ElectricalIntervalStore(chunk_size=chunk_size)
    try:
        with Path(path).open('r', encoding='utf-8', newline='') as stream:
            reader = _Reader(stream, _read_size)
            def payload_member(key):
                return reader.intervals(store) if key == 'intervals' else reader.value()
            record = reader.object(lambda key: reader.object(payload_member)
                                   if key == 'payload' else reader.value())
            reader.whitespace()
            if reader.peek():
                raise ValueError("trailing attribution JSON content")
        if 'payload' not in record or 'attribution_result_sha256' not in record:
            raise ValueError("missing attribution record content")
        payload = record['payload']
        if 'intervals' not in payload:
            raise ValueError("missing attribution intervals")
        store.seal()
        source = DetailedDCAttributionResult.freeze(payload, _decoded=True)
        if source.attribution_result_sha256 != record['attribution_result_sha256']:
            raise ValueError("attribution energy source hash mismatch")
        yield source, payload
    finally:
        store.close()
