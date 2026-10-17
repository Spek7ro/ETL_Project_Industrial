"""Ejecuta el flujo completo: ingesta (si faltan datos) -> ETL -> entrenamiento.

Uso:
    python run_pipeline.py              # descarga el dataset solo si no está en Data/landing
    python run_pipeline.py --download   # fuerza una nueva descarga
"""
import sys

from src.etl.pipeline import run_etl
from src.models.train import train

if __name__ == "__main__":
    run_etl(download="--download" in sys.argv)
    train()
