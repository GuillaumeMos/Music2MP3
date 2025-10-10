# logging_setup.py
import logging
import sys

def setup_logging(log_path="music2mp3.log", level="INFO"):
    """Configure un logging console + fichier, format simple."""
    lvl = getattr(logging, level.upper(), logging.INFO)
    fmt = "%(asctime)s %(levelname)s %(name)s: %(message)s"

    handlers = [logging.StreamHandler(sys.stdout)]
    try:
        handlers.append(logging.FileHandler(log_path, encoding="utf-8"))
    except Exception:
        # si on ne peut pas écrire le fichier (droits, read-only…), on garde la console
        pass

    logging.basicConfig(level=lvl, format=fmt, handlers=handlers)
