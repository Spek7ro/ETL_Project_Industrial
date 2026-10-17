"""Orquestador del pipeline ETL completo."""
from src.etl.extract import extract
from src.etl.ingest_data import ingest_data, landing_complete
from src.etl.load import load
from src.etl.transform import transform


def run_etl(download: bool = False):
    if download or not landing_complete():
        ingest_data(force=download)
    tables, features, limits, summary, report = transform(extract())
    load(tables, features, limits, summary, report)
    return tables, features


if __name__ == "__main__":
    import sys

    run_etl(download="--download" in sys.argv)
