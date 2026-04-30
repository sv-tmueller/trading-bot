from __future__ import annotations

from tools.brokers.base import BaseBroker
from tools.brokers.alpaca import AlpacaBroker
from config import settings


_BROKERS: dict = {
    "alpaca": AlpacaBroker,
}


def get_broker() -> BaseBroker:
    """Return a ``BaseBroker`` instance for the broker named in ``settings.BROKER``.

    The set of valid names is also enforced at import time in
    ``config/settings.py`` — invalid values fail fast at startup, not on the
    first order. Construction is intentionally cheap (no SDK clients are
    instantiated until the first method call) so callers can fetch a broker
    per-request without overhead.
    """
    cls = _BROKERS.get(settings.BROKER)
    if cls is None:
        raise ValueError(
            f"Unknown broker {settings.BROKER!r}. "
            f"Valid options: {sorted(_BROKERS)}"
        )
    return cls()


__all__ = ["BaseBroker", "AlpacaBroker", "get_broker"]
