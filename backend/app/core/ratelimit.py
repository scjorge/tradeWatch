"""Rate limiting em memória (janela deslizante).

Suficiente para uma instância da API. Com várias réplicas, trocar o backend por
Redis mantendo a mesma interface. O bloqueio por tentativas de login fica no
banco (users.failed_login_count/locked_until) e vale para todas as réplicas.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from app.core.errors import TooManyRequests


class SlidingWindowLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, window_seconds: int = 60) -> None:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > window_seconds:
                q.popleft()
            if len(q) >= limit:
                raise TooManyRequests("Muitas tentativas. Aguarde alguns instantes e tente novamente.")
            q.append(now)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = SlidingWindowLimiter()
