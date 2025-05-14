# F1 RaceFlux - Formula 1 Data Pipeline

A comprehensive real-time Formula 1 data processing pipeline, visualization, and analytics platform. This project collects, processes, and visualizes F1 telemetry data using a modern data engineering stack.

## 🏎️ Overview

F1 RaceFlux is a complete data pipeline that:
- Captures real-time Formula 1 race telemetry data
- Processes and enriches the data using Apache Spark
- Stores the processed data in MongoDB
- Provides RESTful API access to the data
- Visualizes race analytics through an interactive Streamlit dashboard

## 🚀 Architecture

The pipeline consists of the following components:

- **Producer**: Collects F1 telemetry data using FastF1 library and publishes to Kafka topics
- **Kafka**: Message broker for data streaming
- **Spark Processor**: Consumes and processes the data streams from Kafka
- **MongoDB**: Stores processed race, telemetry, and analytics data
- **API**: Provides RESTful endpoints for accessing the processed data
- **Streamlit App**: Interactive dashboard for data visualization and race analytics

## 🛠️ Technologies Used

- **Apache Kafka**: Real-time data streaming
- **Apache Spark**: Distributed data processing
- **MongoDB**: NoSQL database for storage
- **FastAPI**: API development
- **Streamlit**: Data visualization and dashboard
- **FastF1**: Formula 1 data collection
- **Docker & Docker Compose**: Containerization and orchestration

## 📊 Features

- Real-time telemetry visualization
- Driver performance comparison
- Race prediction and simulation
- Track speed heatmaps
- Lap time analysis
- Historical data analysis
- Race result summaries

## 🏁 Getting Started

### Prerequisites

- Docker and Docker Compose
- Git

### Installation & Setup

1. Clone the repository:
   ```
   git clone https://github.com/yourusername/f1-data-pipeline.git
   cd f1-data-pipeline
   ```

2. Start the services using Docker Compose:
   ```
   docker-compose up -d
   ```

3. Access the applications:
   - Streamlit Dashboard: http://localhost:8501
   - API: http://localhost:8000/docs

## 📝 Usage

1. Open the Streamlit dashboard
2. Select a race year, Grand Prix, and session type
3. Click "Process Data" to fetch and process the data
4. Explore the various visualization tabs:
   - Race Results
   - Telemetry Visualization
   - Lap Comparison
   - Driver Simulation
   - Track Speed Heatmap
   - Race Predictions



