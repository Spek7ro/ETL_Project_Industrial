"""Ejecuta el flujo completo: ingesta (opcional) -> ETL -> entrenamiento.

Uso:
    python run_pipeline.py              # ETL + entrenamiento con los datos de landing
    python run_pipeline.py --download   # descarga primero el dataset desde Kaggle
"""
import sys

from src.etl.pipeline import run_etl
from src.models.train import train

if __name__ == "__main__":
    run_etl(download="--download" in sys.argv)
    train()
