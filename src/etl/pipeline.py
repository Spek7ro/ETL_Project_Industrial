"""Orquestador del pipeline ETL completo."""
from src.etl.extract import extract
from src.etl.ingest_data import ingest_data
from src.etl.load import load
from src.etl.transform import transform


def run_etl(download: bool = False):
    if download:
        ingest_data()
    df = extract()
    clean, report = transform(df)
    load(clean, report)
    return clean, report


if __name__ == "__main__":
    import sys

    run_etl(download="--download" in sys.argv)
