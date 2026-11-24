"""Очередь слов из напоминания.

Напоминание обещает конкретные слова — сессия повторения обязана начать с них.
Очередь живёт в памяти, как и FSM: при перезапуске сбрасывается, это допустимо.
"""
_pending: dict[int, list[str]] = {}


def set_queue(uid: int, words) -> None:
    _pending[uid] = list(words)


def take_next(uid: int) -> str | None:
    q = _pending.get(uid)
    if not q:
        _pending.pop(uid, None)
        return None
    return q.pop(0)


def clear(uid: int) -> None:
    _pending.pop(uid, None)
