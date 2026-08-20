"""WSGI entrypoint for production servers.

Run with:
    gunicorn wsgi:app
"""

from __future__ import annotations

import os
from pathlib import Path

from dashboard import BASE_DIR, create_app, resolve_app_path


resultados_dir = os.getenv("NERIAS_RESULTADOS_DIR")
resultados = resolve_app_path(Path(resultados_dir)) if resultados_dir else BASE_DIR / "resultados"
app = create_app(resultados)
