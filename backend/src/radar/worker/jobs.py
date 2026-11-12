"""Jobs executados pelo worker.

Cada job é uma função de módulo (o RQ a encontra pelo caminho), recebe só ids e abre a própria
sessão de banco com o escopo da empresa.
"""

from __future__ import annotations

from datetime import timedelta

from radar.logs import get_logger
from radar.worker.runner import periodic

log = get_logger(__name__)


@periodic("heartbeat", every=timedelta(minutes=5))
def heartbeat() -> None:
    """Prova de vida do conjunto agendador → fila → worker."""
    log.info("heartbeat")
