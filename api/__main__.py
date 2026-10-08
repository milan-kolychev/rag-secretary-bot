"""Точка входа: `python -m api`."""

import logging
import sys

import uvicorn
from pydantic import ValidationError

from api.app import create_app
from api.config import format_errors, get_settings
from api.engine import load_engine


def main() -> None:
    """Читает настройки, загружает RAG-движок и запускает сервер."""
    try:
        settings = get_settings()
    except ValidationError as exc:
        sys.exit(f"Invalid configuration, check .env:\n{format_errors(exc)}")

    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        engine = load_engine(settings.rag_engine)
    except ValueError as exc:
        sys.exit(str(exc))
    logging.getLogger(__name__).info("RAG engine: %s", settings.rag_engine)

    app = create_app(settings, engine)
    # Request logs come from the app middleware, uvicorn's access log would duplicate them.
    uvicorn.run(app, host=settings.api_host, port=settings.api_port, access_log=False)


if __name__ == "__main__":
    main()
