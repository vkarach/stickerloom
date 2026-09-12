import logging
import logging.config
from datetime import datetime
from pathlib import Path


class CenteredLevelFormatter(logging.Formatter):
    def format(self, record):
        record.levelname = record.levelname.center(8)
        return super().format(record)


BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

timestamp = datetime.now().strftime("%d.%m.%Y_%H-%M-%S")
LOG_FILE = LOG_DIR / f"log_{timestamp}.log"

LOG_LEVEL = "DEBUG"

NOISY_LOGGERS = ["asyncio", "aiogram.event"]

LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "detailed": {
            "()": CenteredLevelFormatter,
            "format": "%(asctime)s %(levelname)s [%(name)s:%(lineno)d] %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
    },
    "handlers": {
        "file": {
            "class": "logging.FileHandler",
            "level": LOG_LEVEL,
            "formatter": "detailed",
            "filename": str(LOG_FILE),
            "encoding": "utf-8",
        },
        "console": {
            "class": "logging.StreamHandler",
            "level": "INFO",
            "formatter": "detailed",
            "stream": "ext://sys.stdout",
        },
    },
    "root": {
        "handlers": ["file", "console"],
        "level": LOG_LEVEL,
    },
}


def setup_logging():
    logging.config.dictConfig(LOGGING_CONFIG)
    for name in NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
    return logging.getLogger()
