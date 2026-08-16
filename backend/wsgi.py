"""WSGI entry point.

Development::

    flask --app wsgi run --debug --port 5000

Production::

    gunicorn --workers 2 --threads 4 --timeout 180 wsgi:app

Note on workers: model training holds the GIL for tens of seconds and the
market-data cache is per-process, so prefer a small number of workers with
threads over many processes.
"""

from __future__ import annotations

import os

from app import create_app

app = create_app(os.environ.get("APP_ENV", "development"))


if __name__ == "__main__":
    app.run(
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "5000")),
        debug=app.config.get("DEBUG", False),
    )
