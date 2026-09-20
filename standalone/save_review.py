"""Request-scoped acknowledgement of editor validation warnings, before commit.

Map parsing, live revision reads, write locks and backups remain mandatory.
External edits require acknowledgement tied to their exact current revision.
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


def revision(payload, current, error_type, message):
    if payload.get('revision') == current:
        return
    # Bind the acknowledgement to an exact live revision, never a TTL or a force flag.
    if not isinstance(payload.get('revision'), str):
        raise error_type(message, 409, 'conflict')
    warn(error_type, message + ' 仍要保存时，将以当前提交的内容覆盖对应记录；修改前文件会备份。（磁盘版本 ' + current + '）', 409, 'conflict')
    payload['revision'] = current


def warn(error_type, issue, status=400, code='invalid_request'):
    state = _current.get()
    if state is None:
        raise error_type(issue, status, code)
    if issue not in state['issues']:
        state['issues'].append(issue)
    checkpoint()


@contextmanager
def checking(error_type, label):
    try:
        yield
    except error_type as error:
        state = _current.get()
        # Storage, stale revision, unreadable files and identity conflicts remain failures.
        if state is None or error.status not in (400, 422) or error.code != 'invalid_request' or error.__cause__ is not None:
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
