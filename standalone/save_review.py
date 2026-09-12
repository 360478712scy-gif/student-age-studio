"""Request-scoped acknowledgement of editor validation warnings, before commit.

Never bypass map parsing, revision checks, write locks, backups or raw-JSON rules.
Calls outside an explicit review request retain the original strict validation.
"""
from contextlib import contextmanager
from contextvars import ContextVar

_current = ContextVar('studio_save_review', default=None)


def perform(writer, payload, error_type):
    state = {'issues': [], 'confirmed': payload.get('_confirmedSaveWarnings', []), 'error': error_type}
    token = _current.set(state)
    try:
        result = writer(payload)
        checkpoint()
        return result
    finally:
        _current.reset(token)


@contextmanager
def checking(error_type, label):
    try:
        yield
    except error_type as error:
        state = _current.get()
        # Storage, stale revision, unreadable files and identity conflicts remain failures.
        if state is None or error.status != 400 or error.code != 'invalid_request' or error.__cause__ is not None:
            raise
        issue = label + '：' + error.message
        if issue not in state['issues']:
            state['issues'].append(issue)


def checkpoint():
    state = _current.get()
    if not state:
        return
    pending = [issue for issue in state['issues'] if issue not in state['confirmed']]
    if pending:
        error = state['error']('当前配置还有未完成或不符合原版要求的内容。', 400, 'save_warnings')
        error.warnings = pending
        raise error
