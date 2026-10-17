FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src
COPY frontend ./frontend
COPY Data/landing ./Data/landing
COPY run_pipeline.py .

# Descarga el dataset (si no se copió), ejecuta el ETL y entrena: la imagen incluye el modelo
RUN python run_pipeline.py

EXPOSE 8000
CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
