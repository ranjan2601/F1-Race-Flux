FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    default-jdk \
    procps \
    && rm -rf /var/lib/apt/lists/*

ENV JAVA_HOME=/usr/lib/jvm/default-java

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY telemetry_viz.py .
COPY race_results.py .
COPY driver_simulation.py .
COPY lap_comparison.py .
COPY track_speed_heatmap.py .
COPY race_predictions.py .
COPY race_prediction_model.py .

RUN mkdir -p /app/predictions/cache \
    && mkdir -p /app/predictions/data \
    && mkdir -p /app/predictions/results \
    && chmod -R 777 /app/predictions

ENV PYSPARK_PYTHON=python3
ENV PYSPARK_DRIVER_PYTHON=python3
ENV PYTHONPATH="${PYTHONPATH}:/app"

EXPOSE 8501

CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]