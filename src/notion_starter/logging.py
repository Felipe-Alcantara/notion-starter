"""Helper de logging do ``notion_starter``.

Por padrão o logger ``notion_starter`` recebe apenas um ``NullHandler`` — o
comportamento padrão e não intrusivo de uma biblioteca. A aplicação que
consome o pacote fica livre para configurar handlers como preferir.

Chame :func:`configure_logging` se quiser os handlers prontos de console
(e, opcionalmente, arquivo rotativo), por exemplo ao rodar o pacote
diretamente como ferramenta.
"""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

LOGGER_NAME = "notion_starter"

_configurado = False


def get_logger() -> logging.Logger:
    """Retorna o logger ``notion_starter``.

    Na primeira chamada o logger recebe um :class:`logging.NullHandler`, de
    forma que importar a biblioteca nunca emite avisos de "No handlers could
    be found" e nunca escreve em lugar nenhum sem a aplicação pedir.

    Returns:
        O logger ``notion_starter``.
    """

    logger = logging.getLogger(LOGGER_NAME)
    if not logger.handlers:
        logger.addHandler(logging.NullHandler())
    return logger


def configure_logging(
    *,
    level: int = logging.INFO,
    console: bool = True,
    log_file: str | Path | None = None,
    max_bytes: int = 5 * 1024 * 1024,
    backup_count: int = 3,
) -> logging.Logger:
    """Anexa handlers de console e/ou arquivo rotativo ao logger.

    Idempotente: chamar mais de uma vez não tem efeito adicional.

    Args:
        level: Nível mínimo do handler de arquivo (e do logger).
        console: Quando verdadeiro, adiciona um handler de console em
            ``WARNING`` ou acima.
        log_file: Caminho opcional para um arquivo de log rotativo. O
            diretório pai é criado se necessário.
        max_bytes: Tamanho máximo do arquivo antes de rotacionar.
        backup_count: Número de backups rotacionados a manter.

    Returns:
        O logger ``notion_starter`` configurado.
    """

    global _configurado
    logger = logging.getLogger(LOGGER_NAME)
    if _configurado:
        return logger

    # Remove o NullHandler padrão, se presente.
    for handler in list(logger.handlers):
        if isinstance(handler, logging.NullHandler):
            logger.removeHandler(handler)

    logger.setLevel(min(level, logging.WARNING))

    if console:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.WARNING)
        console_handler.setFormatter(
            logging.Formatter(fmt="[notion_starter] %(levelname)s — %(message)s")
        )
        logger.addHandler(console_handler)

    if log_file is not None:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        logger.addHandler(file_handler)

    logger.propagate = False
    _configurado = True
    return logger
