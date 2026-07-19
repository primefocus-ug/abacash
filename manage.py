#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys
from pathlib import Path


def _add_local_venv_site_packages():
    project_root = Path(__file__).resolve().parent
    candidates = []
    if os.name == "nt":
        candidates.append(project_root / "venv" / "Lib" / "site-packages")
    else:
        candidates.append(
            project_root
            / "venv"
            / "lib"
            / f"python{sys.version_info.major}.{sys.version_info.minor}"
            / "site-packages"
        )

    for path in candidates:
        if path.exists():
            site_path = str(path)
            if site_path not in sys.path:
                sys.path.insert(0, site_path)
            break


_add_local_venv_site_packages()


def main():
    """Run administrative tasks."""
    # Use the local config package (SQLite-friendly) provided with this project.
    os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings"
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
