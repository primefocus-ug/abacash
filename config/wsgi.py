import os
import sys
from pathlib import Path

from django.core.wsgi import get_wsgi_application

project_root = Path(__file__).resolve().parent.parent
if os.name == "nt":
    venv_site = project_root / "venv" / "Lib" / "site-packages"
else:
    venv_site = (
        project_root
        / "venv"
        / "lib"
        / f"python{sys.version_info.major}.{sys.version_info.minor}"
        / "site-packages"
    )

if venv_site.exists():
    site_path = str(venv_site)
    if site_path not in sys.path:
        sys.path.insert(0, site_path)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

application = get_wsgi_application()
