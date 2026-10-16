"""Worker: processa a fila de sincronização e as tarefas periódicas dos módulos.

Usa o mesmo código-base da API. Vários workers podem rodar em paralelo: a fila
usa ``FOR UPDATE SKIP LOCKED`` e cada job é processado por apenas um deles.
"""

from __future__ import annotations

import logging
import os
import signal
import socket
import time

from sqlalchemy.dialects.postgresql import insert

from app.config import get_settings
from app.core.logging import setup_logging
from app.db import session_factory
from app.models import WorkerHeartbeat
from app.models.base import utcnow
from app.modules.registry import REGISTRY
from app.modules.trades.sync import claim_next_job, run_sync_job

log = logging.getLogger("app.worker")
_stop = False


def _handle_stop(*_):
    global _stop
    _stop = True
    log.info("worker_stopping")


def heartbeat(worker_id: str, info: dict) -> None:
    with session_factory()() as db:
        db.execute(
            insert(WorkerHeartbeat)
            .values(worker_id=worker_id, last_seen=utcnow(), info=info)
            .on_conflict_do_update(index_elements=["worker_id"], set_={"last_seen": utcnow(), "info": info})
        )
        db.commit()


def run() -> None:
    s = get_settings()
    setup_logging(s.log_level)
    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)
    worker_id = f"{socket.gethostname()}-{os.getpid()}"
    tasks = [t for m in REGISTRY for t in m.periodic_tasks]
    last_run: dict[str, float] = {}
    stats = {"jobs": 0, "task_errors": 0}
    last_hb = 0.0
    log.info("worker_started", extra={"worker_id": worker_id, "tasks": [t.name for t in tasks]})

    while not _stop:
        now = time.monotonic()
        if now - last_hb > 20:
            try:
                heartbeat(worker_id, stats)
                last_hb = now
            except Exception:  # noqa: BLE001
                log.exception("heartbeat_failed")

        for t in tasks:
            if now - last_run.get(t.name, 0) >= t.interval_seconds:
                last_run[t.name] = now
                try:
                    with session_factory()() as db:
                        t.run(db)
                except Exception:  # noqa: BLE001 - uma tarefa com falha não derruba as demais
                    stats["task_errors"] += 1
                    log.exception("periodic_task_failed", extra={"task": t.name})

        processed = False
        try:
            with session_factory()() as db:
                job = claim_next_job(db, worker_id)
                if job is not None:
                    processed = True
                    stats["jobs"] += 1
                    log.info("job_started", extra={"job_id": str(job.id), "connection_id": str(job.connection_id)})
                    run_sync_job(db, job)
        except Exception:  # noqa: BLE001
            log.exception("job_loop_error")
            time.sleep(5)
        if not processed:
            time.sleep(s.worker_poll_seconds)
    log.info("worker_stopped")


if __name__ == "__main__":
    run()
