from contextlib import contextmanager


@contextmanager
def capture_signals(*signals):
    calls = []

    def _receiver(*args, **kwargs):
        calls.append((args, kwargs))

    for signal in signals:
        signal.connect(_receiver)
    try:
        yield calls
    finally:
        for signal in signals:
            signal.disconnect(_receiver)
