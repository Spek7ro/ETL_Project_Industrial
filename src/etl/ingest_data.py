"""Ingesta: descarga el dataset Microsoft Azure Predictive Maintenance a la zona de landing.

Fuentes, en orden: Kaggle (kagglehub) y, si no está disponible, la réplica pública
en GitHub. Tras la descarga se verifica el número de filas de cada archivo.
"""
import glob
import os
import shutil
import urllib.request

from src.config import EXPECTED_ROWS, KAGGLE_DATASET, LANDING_DIR, MIRROR_BASE_URL, SOURCE_FILES


def landing_complete() -> bool:
    return all((LANDING_DIR / name).exists() for name in SOURCE_FILES.values())


def _from_kaggle() -> None:
    import kagglehub

    path = kagglehub.dataset_download(KAGGLE_DATASET)
    for name in SOURCE_FILES.values():
        matches = glob.glob(os.path.join(path, "**", name), recursive=True)
        if not matches:
            raise FileNotFoundError(f"{name} no está en la descarga de Kaggle")
        shutil.copy(matches[0], LANDING_DIR / name)


def _from_mirror() -> None:
    for name in SOURCE_FILES.values():
        url = f"{MIRROR_BASE_URL}/{name}"
        print(f"  {url}")
        tmp = LANDING_DIR / f".{name}.part"
        urllib.request.urlretrieve(url, tmp)
        tmp.replace(LANDING_DIR / name)


def verify_landing() -> None:
    for key, name in SOURCE_FILES.items():
        with open(LANDING_DIR / name, encoding="utf-8") as fh:
            rows = sum(1 for _ in fh) - 1
        if rows != EXPECTED_ROWS[key]:
            raise ValueError(f"{name}: {rows} filas, se esperaban {EXPECTED_ROWS[key]} (descarga corrupta)")


def ingest_data(force: bool = False) -> None:
    os.makedirs(LANDING_DIR, exist_ok=True)
    if landing_complete() and not force:
        print(f"[ingest] Datos ya presentes en {LANDING_DIR}; se omite la descarga (use --force).")
        return

    try:
        print("[ingest] Descargando desde Kaggle…")
        _from_kaggle()
    except Exception as exc:  # sin credenciales, sin red a Kaggle, etc.
        print(f"[ingest] Kaggle no disponible ({type(exc).__name__}); usando la réplica de GitHub…")
        _from_mirror()

    verify_landing()
    print(f"[ingest] Dataset verificado en {LANDING_DIR}")


if __name__ == "__main__":
    import sys

    ingest_data(force="--force" in sys.argv)
