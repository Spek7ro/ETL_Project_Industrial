"""Ingesta: descarga el dataset desde Kaggle hacia la zona de landing."""
import glob
import os
import shutil

from src.config import KAGGLE_DATASET, LANDING_DIR


def ingest_data(force: bool = False) -> None:
    os.makedirs(LANDING_DIR, exist_ok=True)

    if not force and glob.glob(os.path.join(LANDING_DIR, "*.csv")):
        print(f"Landing ya contiene datos en {LANDING_DIR}; se omite la descarga (use --force).")
        return

    import kagglehub

    print("Downloading dataset from Kaggle...")
    path = kagglehub.dataset_download(KAGGLE_DATASET)
    print("Path to downloaded files:", path)

    csv_files = glob.glob(os.path.join(path, "*.csv"))
    if not csv_files:
        print("No CSV files found in the downloaded dataset.")
        return

    for csv_file in csv_files:
        filename = os.path.basename(csv_file)
        shutil.copy(csv_file, os.path.join(LANDING_DIR, filename))
        print(f"Moved {filename} to {LANDING_DIR}")


if __name__ == "__main__":
    import sys

    ingest_data(force="--force" in sys.argv)
