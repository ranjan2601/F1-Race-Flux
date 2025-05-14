#!/usr/bin/env python
import time
import json
import fastf1
import pandas as pd
from kafka import KafkaProducer
from kafka.errors import NoBrokersAvailable
import argparse
import os
import logging
import signal
import sys
import uuid

# Set up logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("F1DataProducer")
# Enable FastF1 cache
cache_dir = "/app/f1_cache"
os.makedirs(cache_dir, exist_ok=True)
fastf1.Cache.enable_cache(cache_dir)
# Kafka configuration
KAFKA_BROKER = os.environ.get("KAFKA_BROKER", "kafka:29092")
LAPS_TOPIC = "telemetry-data"
TELEMETRY_TOPIC = "car-telemetry-data"
POSITION_TOPIC = "car-position-data"
DRIVER_INFO_TOPIC = "driver-info-data"
RESULTS_TOPIC = "race-results-data"
WEATHER_TOPIC = "weather-data"
# Flag to control graceful shutdown
running = True


def signal_handler(sig, frame):
    global running
    logger.info("Received termination signal. Shutting down gracefully...")
    running = False


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


def parse_args():
    parser = argparse.ArgumentParser(description="F1 Data Producer")
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--event", type=str, required=True)
    parser.add_argument("--session", type=str, required=True)
    parser.add_argument(
        "--prediction-mode", action="store_true", help="Run in prediction mode"
    )
    parser.add_argument(
        "--source-years",
        type=str,
        default="2022,2023,2024",
        help="Source years for prediction data",
    )
    return parser.parse_args()


def init_kafka_producer():
    max_retries = 10
    retry_interval = 5
    for attempt in range(max_retries):
        try:
            logger.info(
                f"Connecting to Kafka at {KAFKA_BROKER} (attempt {attempt + 1}/{max_retries})..."
            )
            producer = KafkaProducer(
                bootstrap_servers=KAFKA_BROKER,
                value_serializer=lambda v: json.dumps(v, default=str).encode("utf-8"),
                max_request_size=10485760,  # 10MB max message size
                buffer_memory=33554432,  # 32MB buffer memory
                batch_size=131072,  # 128KB batch size
                linger_ms=50,  # Wait 50ms for batching
                compression_type="gzip",  # Use compression for efficiency
                acks=1,
            )
            logger.info("Kafka connection successful!")
            return producer
        except NoBrokersAvailable:
            logger.warning(f"No brokers available. Retrying in {retry_interval}s...")
            time.sleep(retry_interval)
        except Exception as e:
            logger.error(f"Kafka connection error: {e}")
            time.sleep(retry_interval)
    return None


def process_prediction_data(args):
    """
    Process data for prediction by loading historical data from source years
    and sending it to Kafka with prediction flags
    """
    try:
        # Get source years
        source_years = [int(y.strip()) for y in args.source_years.split(",")]
        logger.info(
            f"Processing prediction data for {args.event} using source years: {source_years}"
        )

        # Connect to Kafka
        producer = init_kafka_producer()
        if not producer:
            logger.error("Could not connect to Kafka. Exiting.")
            return 1

        # Process each source year
        for source_year in source_years:
            try:
                # Try to find an event with the same name in the source year
                source_schedule = fastf1.get_event_schedule(source_year)
                source_event = None

                for _, event in source_schedule.iterrows():
                    if (
                        args.event.lower() in event["EventName"].lower()
                        or event["EventName"].lower() in args.event.lower()
                    ):
                        source_event = event["EventName"]
                        break

                if not source_event:
                    # If no exact match, try location or country
                    for _, event in source_schedule.iterrows():
                        if (
                            args.event.lower() in event["Location"].lower()
                            or args.event.lower() in event["Country"].lower()
                        ):
                            source_event = event["EventName"]
                            break

                if not source_event:
                    logger.warning(
                        f"Could not find a matching event for {args.event} in {source_year}"
                    )
                    continue

                logger.info(f"Found matching event in {source_year}: {source_event}")

                # Load the session
                session = fastf1.get_session(source_year, source_event, "R")
                session.load()
                logger.info(
                    f"Successfully loaded session data for {source_year} {source_event}"
                )

                # =================== LAP DATA ===================
                logger.info(f"Processing lap data from {source_year} {source_event}")
                laps = session.laps
                lap_data = []
                for _, lap in laps.iterrows():
                    lap_dict = lap.to_dict()
                    lap_dict["Year"] = source_year
                    lap_dict["GrandPrix"] = source_event
                    lap_dict["SessionType"] = "Race"
                    lap_dict["IsPrediction"] = True
                    lap_dict["SourceYear"] = source_year
                    lap_dict["SourceEvent"] = source_event

                    # Convert data types for JSON serialization
                    for key, value in lap_dict.items():
                        if pd.isna(value):
                            lap_dict[key] = None
                        elif isinstance(value, pd.Timestamp):
                            lap_dict[key] = value.isoformat()

                    lap_data.append(lap_dict)

                # Stream lap data to Kafka
                if lap_data:
                    stream_to_kafka(producer, "lap", lap_data, LAPS_TOPIC)
                    logger.info(
                        f"Sent {len(lap_data)} lap records from {source_year} {source_event} to Kafka"
                    )

                # =================== DRIVER INFO ===================
                logger.info(
                    f"Processing driver info data from {source_year} {source_event}"
                )
                driver_info_list = []
                if (
                    hasattr(session, "results")
                    and session.results is not None
                    and not session.results.empty
                ):
                    results_df = session.results
                    for _, row in results_df.iterrows():
                        driver_info = {
                            "Driver": row.get("Abbreviation", None),
                            "DriverNumber": row.get("DriverNumber", None),
                            "FullName": row.get("FullName", None)
                            or f"{row.get('FirstName', '')} {row.get('LastName', '')}",
                            "Abbreviation": row.get("Abbreviation", None),
                            "TeamName": row.get("TeamName", None),
                            "Nationality": row.get("Nationality", None)
                            or row.get("CountryCode", None),
                            "Year": source_year,
                            "GrandPrix": source_event,
                            "SessionType": "Race",
                            "DataType": "DriverInfo",
                            "RecordId": str(uuid.uuid4()),
                            "IsPrediction": True,
                            "SourceYear": source_year,
                            "SourceEvent": source_event,
                        }
                        driver_info_list.append(driver_info)

                # Stream driver info to Kafka
                if driver_info_list:
                    stream_to_kafka(
                        producer, "driver_info", driver_info_list, DRIVER_INFO_TOPIC
                    )
                    logger.info(
                        f"Sent {len(driver_info_list)} driver info records from {source_year} {source_event} to Kafka"
                    )

                # =================== RACE RESULTS ===================
                logger.info(
                    f"Processing race results data from {source_year} {source_event}"
                )
                results_list = []
                if (
                    hasattr(session, "results")
                    and session.results is not None
                    and not session.results.empty
                ):
                    results_df = session.results
                    for _, row in results_df.iterrows():
                        row_dict = row.to_dict()
                        result = {
                            "Driver": row_dict.get("Abbreviation", None),
                            "DriverNumber": row_dict.get("DriverNumber", None),
                            "Position": row_dict.get("Position", None),
                            "ClassifiedPosition": row_dict.get(
                                "ClassifiedPosition", None
                            ),
                            "GridPosition": row_dict.get("GridPosition", None),
                            "Q1": row_dict.get("Q1", None),
                            "Q2": row_dict.get("Q2", None),
                            "Q3": row_dict.get("Q3", None),
                            "Time": row_dict.get("Time", None),
                            "Status": row_dict.get("Status", None),
                            "Points": row_dict.get("Points", None),
                            "TeamName": row_dict.get("TeamName", None),
                            "Year": source_year,
                            "GrandPrix": source_event,
                            "SessionType": "Race",
                            "DataType": "RaceResults",
                            "RecordId": str(uuid.uuid4()),
                            "IsPrediction": True,
                            "SourceYear": source_year,
                            "SourceEvent": source_event,
                        }

                        # Convert specific data types
                        for key, value in result.items():
                            if pd.isna(value):
                                result[key] = None
                            elif isinstance(value, pd.Timestamp):
                                result[key] = value.isoformat()
                            # Convert numpy types to Python native types
                            elif hasattr(value, "item") and callable(
                                getattr(value, "item")
                            ):
                                try:
                                    result[key] = value.item()
                                except:
                                    result[key] = (
                                        float(value)
                                        if isinstance(value, (int, float, complex))
                                        else str(value)
                                    )

                        results_list.append(result)

                # Stream race results to Kafka
                if results_list:
                    stream_to_kafka(
                        producer, "race_results", results_list, RESULTS_TOPIC
                    )
                    logger.info(
                        f"Sent {len(results_list)} race results records from {source_year} {source_event} to Kafka"
                    )

                # =================== CAR TELEMETRY ===================
                logger.info(
                    f"Processing car telemetry data from {source_year} {source_event}"
                )
                all_drivers = session.drivers

                for driver in all_drivers:
                    try:
                        driver_laps = laps.pick_driver(driver)
                        if driver_laps is None or driver_laps.empty:
                            continue

                        # Process all laps (no downsampling)
                        for _, lap in driver_laps.iterrows():
                            try:
                                lap_number = lap["LapNumber"]
                                car_data = lap.get_car_data()

                                if car_data is None or car_data.empty:
                                    continue

                                # Process all telemetry points (no downsampling)
                                telemetry_batch = []
                                for _, row in car_data.iterrows():
                                    telemetry_dict = row.to_dict()
                                    telemetry_dict["Driver"] = driver
                                    telemetry_dict["LapNumber"] = lap_number
                                    telemetry_dict["Year"] = source_year
                                    telemetry_dict["GrandPrix"] = source_event
                                    telemetry_dict["SessionType"] = "Race"
                                    telemetry_dict["DataType"] = "Telemetry"
                                    telemetry_dict["RecordId"] = str(uuid.uuid4())
                                    telemetry_dict["IsPrediction"] = True
                                    telemetry_dict["SourceYear"] = source_year
                                    telemetry_dict["SourceEvent"] = source_event

                                    # Convert data types for JSON serialization
                                    for key, value in telemetry_dict.items():
                                        if pd.isna(value):
                                            telemetry_dict[key] = None
                                        elif isinstance(value, pd.Timestamp):
                                            telemetry_dict[key] = value.isoformat()

                                    telemetry_batch.append(telemetry_dict)

                                    # Send in smaller batches to avoid memory issues
                                    if len(telemetry_batch) >= 500:
                                        stream_to_kafka(
                                            producer,
                                            "telemetry",
                                            telemetry_batch,
                                            TELEMETRY_TOPIC,
                                        )
                                        telemetry_batch = []

                                # Send any remaining records
                                if telemetry_batch:
                                    stream_to_kafka(
                                        producer,
                                        "telemetry",
                                        telemetry_batch,
                                        TELEMETRY_TOPIC,
                                    )

                            except Exception as e:
                                logger.error(
                                    f"Error processing telemetry for driver {driver}, lap {lap_number}: {e}"
                                )
                                continue
                    except Exception as e:
                        logger.error(
                            f"Error processing telemetry for driver {driver}: {e}"
                        )
                        continue

                # =================== CAR POSITION ===================
                logger.info(
                    f"Processing car position data from {source_year} {source_event}"
                )

                for driver in all_drivers:
                    try:
                        driver_laps = laps.pick_driver(driver)
                        if driver_laps is None or driver_laps.empty:
                            continue

                        # Process all laps (no downsampling)
                        for _, lap in driver_laps.iterrows():
                            try:
                                lap_number = lap["LapNumber"]
                                pos_data = lap.get_pos_data()

                                if pos_data is None or pos_data.empty:
                                    continue

                                # Process all position points (no downsampling)
                                position_batch = []
                                for _, row in pos_data.iterrows():
                                    position_dict = row.to_dict()
                                    position_dict["Driver"] = driver
                                    position_dict["LapNumber"] = lap_number
                                    position_dict["Year"] = source_year
                                    position_dict["GrandPrix"] = source_event
                                    position_dict["SessionType"] = "Race"
                                    position_dict["DataType"] = "Position"
                                    position_dict["RecordId"] = str(uuid.uuid4())
                                    position_dict["IsPrediction"] = True
                                    position_dict["SourceYear"] = source_year
                                    position_dict["SourceEvent"] = source_event

                                    # Convert data types for JSON serialization
                                    for key, value in position_dict.items():
                                        if pd.isna(value):
                                            position_dict[key] = None
                                        elif isinstance(value, pd.Timestamp):
                                            position_dict[key] = value.isoformat()

                                    position_batch.append(position_dict)

                                    # Send in smaller batches to avoid memory issues
                                    if len(position_batch) >= 500:
                                        stream_to_kafka(
                                            producer,
                                            "position",
                                            position_batch,
                                            POSITION_TOPIC,
                                        )
                                        position_batch = []

                                # Send any remaining records
                                if position_batch:
                                    stream_to_kafka(
                                        producer,
                                        "position",
                                        position_batch,
                                        POSITION_TOPIC,
                                    )

                            except Exception as e:
                                logger.error(
                                    f"Error processing position data for driver {driver}, lap {lap_number}: {e}"
                                )
                                continue
                    except Exception as e:
                        logger.error(
                            f"Error processing position data for driver {driver}: {e}"
                        )
                        continue

                # =================== WEATHER DATA ===================
                logger.info(
                    f"Processing weather data from {source_year} {source_event}"
                )
                weather_data = []
                if (
                    hasattr(session, "weather_data")
                    and session.weather_data is not None
                    and not session.weather_data.empty
                ):
                    weather_df = session.weather_data
                    for _, row in weather_df.iterrows():
                        weather_record = row.to_dict()
                        weather_record["Year"] = source_year
                        weather_record["GrandPrix"] = source_event
                        weather_record["SessionType"] = "Race"
                        weather_record["DataType"] = "Weather"
                        weather_record["RecordId"] = str(uuid.uuid4())
                        weather_record["IsPrediction"] = True
                        weather_record["SourceYear"] = source_year
                        weather_record["SourceEvent"] = source_event

                        # Convert data types for JSON serialization
                        for key, value in weather_record.items():
                            if pd.isna(value):
                                weather_record[key] = None
                            elif isinstance(value, pd.Timestamp):
                                weather_record[key] = value.isoformat()

                        weather_data.append(weather_record)

                # Stream weather data to Kafka
                if weather_data:
                    stream_to_kafka(producer, "weather", weather_data, WEATHER_TOPIC)
                    logger.info(
                        f"Sent {len(weather_data)} weather records from {source_year} {source_event} to Kafka"
                    )

            except Exception as e:
                logger.error(f"Error processing source year {source_year}: {e}")
                import traceback

                logger.error(traceback.format_exc())

        producer.close()
        logger.info("Prediction data processing completed successfully")
        return 0

    except Exception as e:
        logger.error(f"Error in prediction processing: {e}")
        return 1


def get_lap_data(session, producer):
    """Get lap data from the session"""
    try:
        laps = session.laps
        event_name = session.event["EventName"]
        logger.info(f"Loaded {len(laps)} laps from {event_name} {session.name}")

        lap_data = []
        for _, lap in laps.iterrows():
            lap_dict = lap.to_dict()
            lap_dict["Year"] = session.event.year
            lap_dict["GrandPrix"] = event_name
            lap_dict["SessionType"] = session.name

            for key, value in lap_dict.items():
                if pd.isna(value):
                    lap_dict[key] = None
                elif isinstance(value, pd.Timestamp):
                    lap_dict[key] = value.isoformat()

            lap_data.append(lap_dict)

        # Stream lap data to Kafka
        if lap_data:
            stream_to_kafka(producer, "lap", lap_data, LAPS_TOPIC)

        return True  # Successfully processed lap data
    except Exception as e:
        logger.error(f"Error getting lap data: {e}")
        return False


def get_telemetry_data(session, producer):
    """Get telemetry data for all drivers in the session with lap information"""
    try:
        all_drivers = session.drivers
        event_name = session.event["EventName"]

        # First, get all laps for reference
        all_laps = session.laps

        for driver in all_drivers:
            try:
                logger.info(f"Fetching telemetry data for driver {driver}")

                # Get driver's laps
                driver_laps = all_laps.pick_driver(driver)

                if driver_laps is None or driver_laps.empty:
                    logger.warning(f"No lap data available for driver {driver}")
                    continue

                # Process each lap individually to ensure correct lap numbers
                for _, lap in driver_laps.iterrows():
                    try:
                        lap_number = lap["LapNumber"]
                        logger.info(
                            f"Processing telemetry for driver {driver}, lap {lap_number}"
                        )

                        # Get telemetry data for this specific lap
                        car_data = lap.get_car_data()

                        if car_data is None or car_data.empty:
                            logger.warning(
                                f"No car data available for driver {driver}, lap {lap_number}"
                            )
                            continue

                        # Process telemetry data in chunks to reduce memory usage
                        chunk_size = 5000
                        total_rows = len(car_data)

                        for chunk_start in range(0, total_rows, chunk_size):
                            if not running:
                                break

                            chunk_end = min(chunk_start + chunk_size, total_rows)
                            logger.info(
                                f"Processing telemetry chunk {chunk_start}-{chunk_end} for driver {driver}, lap {lap_number}"
                            )

                            telemetry_chunk = []
                            for i in range(chunk_start, chunk_end):
                                if i >= len(car_data):
                                    break

                                row = car_data.iloc[i]

                                telemetry_dict = row.to_dict()
                                telemetry_dict["Driver"] = driver
                                telemetry_dict["LapNumber"] = lap_number
                                telemetry_dict["Year"] = session.event.year
                                telemetry_dict["GrandPrix"] = event_name
                                telemetry_dict["SessionType"] = session.name
                                telemetry_dict["DataType"] = "Telemetry"
                                telemetry_dict["RecordId"] = str(uuid.uuid4())

                                for key, value in telemetry_dict.items():
                                    if pd.isna(value):
                                        telemetry_dict[key] = None
                                    elif isinstance(value, pd.Timestamp):
                                        telemetry_dict[key] = value.isoformat()

                                telemetry_chunk.append(telemetry_dict)

                            # Stream this chunk directly to Kafka
                            stream_to_kafka(
                                producer, "telemetry", telemetry_chunk, TELEMETRY_TOPIC
                            )

                            # Clear chunk data to free memory
                            telemetry_chunk = []

                    except Exception as e:
                        logger.error(
                            f"Error processing telemetry for driver {driver}, lap {lap_number}: {e}"
                        )
                        continue

            except Exception as e:
                logger.error(f"Error processing telemetry for driver {driver}: {e}")
                continue

        return True  # Successfully processed all drivers

    except Exception as e:
        logger.error(f"Error getting telemetry data: {e}")
        return False


def get_position_data(session, producer):
    """Get position data for all drivers in the session with lap information"""
    try:
        all_drivers = session.drivers
        event_name = session.event["EventName"]

        # First, get all laps for reference
        all_laps = session.laps

        for driver in all_drivers:
            try:
                logger.info(f"Fetching position data for driver {driver}")

                # Get driver's laps
                driver_laps = all_laps.pick_driver(driver)

                if driver_laps is None or driver_laps.empty:
                    logger.warning(f"No lap data available for driver {driver}")
                    continue

                # Process each lap individually to ensure correct lap numbers
                for _, lap in driver_laps.iterrows():
                    try:
                        lap_number = lap["LapNumber"]
                        logger.info(
                            f"Processing position data for driver {driver}, lap {lap_number}"
                        )

                        # Get position data for this specific lap
                        pos_data = lap.get_pos_data()

                        if pos_data is None or pos_data.empty:
                            logger.warning(
                                f"No position data available for driver {driver}, lap {lap_number}"
                            )
                            continue

                        # Process position data in chunks to reduce memory usage
                        chunk_size = 5000
                        total_rows = len(pos_data)

                        for chunk_start in range(0, total_rows, chunk_size):
                            if not running:
                                break

                            chunk_end = min(chunk_start + chunk_size, total_rows)
                            logger.info(
                                f"Processing position chunk {chunk_start}-{chunk_end} for driver {driver}, lap {lap_number}"
                            )

                            position_chunk = []
                            for i in range(chunk_start, chunk_end):
                                if i >= len(pos_data):
                                    break

                                row = pos_data.iloc[i]

                                position_dict = row.to_dict()
                                position_dict["Driver"] = driver
                                position_dict["LapNumber"] = lap_number
                                position_dict["Year"] = session.event.year
                                position_dict["GrandPrix"] = event_name
                                position_dict["SessionType"] = session.name
                                position_dict["DataType"] = "Position"
                                position_dict["RecordId"] = str(uuid.uuid4())

                                for key, value in position_dict.items():
                                    if pd.isna(value):
                                        position_dict[key] = None
                                    elif isinstance(value, pd.Timestamp):
                                        position_dict[key] = value.isoformat()

                                position_chunk.append(position_dict)

                            # Stream this chunk directly to Kafka
                            stream_to_kafka(
                                producer, "position", position_chunk, POSITION_TOPIC
                            )

                            # Clear chunk data to free memory
                            position_chunk = []

                            # Log progress for each chunk
                            logger.info(
                                f"Processed position chunk {chunk_start}-{chunk_end} for driver {driver}, lap {lap_number}"
                            )

                    except Exception as e:
                        logger.error(
                            f"Error processing position data for driver {driver}, lap {lap_number}: {e}"
                        )
                        continue

            except Exception as e:
                logger.error(f"Error processing position data for driver {driver}: {e}")
                continue

        return True  # Successfully processed all drivers

    except Exception as e:
        logger.error(f"Error getting position data: {e}")
        return False


def get_driver_info(session, producer):
    """Get driver information from the session"""
    try:
        event_name = session.event["EventName"]
        logger.info(f"Fetching driver information from {event_name} {session.name}")
        # Get the driver information from the session
        driver_info_list = []
        # In FastF1, driver info can be extracted from the session.results DataFrame if available
        if (
            hasattr(session, "results")
            and session.results is not None
            and not session.results.empty
        ):
            results_df = session.results
            for (
                _,
                row,
            ) in (
                results_df.iterrows()
            ):  # FIXED: Corrected variable name from resultsdf to results_df
                driver_info = {
                    "Driver": row.get("Abbreviation", None),
                    "DriverNumber": row.get("DriverNumber", None),
                    "FullName": row.get("FullName", None)
                    or f"{row.get('FirstName', '')} {row.get('LastName', '')}",
                    "Abbreviation": row.get("Abbreviation", None),
                    "TeamName": row.get("TeamName", None),
                    "Nationality": row.get("Nationality", None)
                    or row.get("CountryCode", None),
                    "Year": session.event.year,
                    "GrandPrix": event_name,
                    "SessionType": session.name,
                    "DataType": "DriverInfo",
                    "RecordId": str(uuid.uuid4()),
                }
                driver_info_list.append(driver_info)
        else:
            # If results are not available, get driver info from session.laps
            unique_drivers = session.laps["Driver"].unique()
            for driver in unique_drivers:
                # Try to get more info about the driver from other sources
                driver_laps = session.laps.pick_driver(driver)
                if not driver_laps.empty:
                    team = (
                        driver_laps["Team"].iloc[0]
                        if "Team" in driver_laps.columns
                        else None
                    )
                    driver_info = {
                        "Driver": driver,
                        "DriverNumber": None,
                        "FullName": None,
                        "Abbreviation": driver,
                        "TeamName": team,
                        "Nationality": None,
                        "Year": session.event.year,
                        "GrandPrix": event_name,
                        "SessionType": session.name,
                        "DataType": "DriverInfo",
                        "RecordId": str(uuid.uuid4()),
                    }
                    driver_info_list.append(driver_info)
        logger.info(f"Found information for {len(driver_info_list)} drivers")
        # Stream to Kafka
        if driver_info_list:
            stream_to_kafka(
                producer, "driver_info", driver_info_list, DRIVER_INFO_TOPIC
            )
        else:
            logger.warning("No driver information found")
        return True
    except Exception as e:
        logger.error(f"Error getting driver information: {e}")
        import traceback

        logger.error(traceback.format_exc())
        return False


def get_race_results(session, producer):
    """Get race results from the session"""
    try:
        event_name = session.event["EventName"]
        logger.info(f"Fetching race results from {event_name} {session.name}")

        # Check session type - handle both abbreviations and full names
        valid_session_types = [
            "R",
            "Q",
            "S",
            "SQ",
            "Race",
            "Qualifying",
            "Sprint",
            "Sprint Qualifying",
        ]
        if session.name not in valid_session_types:
            logger.info(
                f"Session type {session.name} is not a race, qualifying, or sprint. Skipping results."
            )
            return True

        # Get the results from the session
        results_list = []

        if (
            hasattr(session, "results")
            and session.results is not None
            and not session.results.empty
        ):
            results_df = session.results

            # Log the columns and a sample row for debugging
            logger.info(f"Results DataFrame columns: {list(results_df.columns)}")
            if len(results_df) > 0:
                sample_row = results_df.iloc[0]
                logger.info(
                    f"Sample row types: {[(col, type(sample_row[col])) for col in results_df.columns]}"
                )
                logger.info(
                    f"Sample Position value: {sample_row.get('Position', 'NOT FOUND')} of type {type(sample_row.get('Position', None))}"
                )

            for _, row in results_df.iterrows():
                row_dict = row.to_dict()

                # Log the actual row data for debugging
                logger.info(
                    f"Processing driver {row_dict.get('Abbreviation', 'Unknown')}, Position: {row_dict.get('Position', 'NOT FOUND')}"
                )

                result = {
                    "Driver": row_dict.get("Abbreviation", None),
                    "DriverNumber": row_dict.get("DriverNumber", None),
                    "Position": row_dict.get("Position", None),
                    "ClassifiedPosition": row_dict.get("ClassifiedPosition", None),
                    "GridPosition": row_dict.get("GridPosition", None),
                    "Q1": row_dict.get("Q1", None),
                    "Q2": row_dict.get("Q2", None),
                    "Q3": row_dict.get("Q3", None),
                    "Time": row_dict.get("Time", None),
                    "Status": row_dict.get("Status", None),
                    "Points": row_dict.get("Points", None),
                    "TeamName": row_dict.get("TeamName", None),
                    "Year": session.event.year,
                    "GrandPrix": event_name,
                    "SessionType": session.name,
                    "DataType": "RaceResults",
                    "RecordId": str(uuid.uuid4()),
                }

                # Add more debugging info
                logger.info(
                    f"Result object for {result['Driver']}: Position={result['Position']}, Points={result['Points']}"
                )

                # Convert specific data types
                for key, value in result.items():
                    if pd.isna(value):
                        result[key] = None
                    elif isinstance(value, pd.Timestamp):
                        result[key] = value.isoformat()
                    # Convert numpy types to Python native types to avoid serialization issues
                    elif hasattr(value, "item") and callable(getattr(value, "item")):
                        try:
                            result[key] = value.item()
                            logger.info(
                                f"Converted {key} from {type(value)} to {type(result[key])}: {result[key]}"
                            )
                        except:
                            # If item() fails, try direct conversion
                            result[key] = (
                                float(value)
                                if isinstance(value, (int, float, complex))
                                else str(value)
                            )
                            logger.info(
                                f"Direct conversion for {key}: {value} -> {result[key]}"
                            )

                results_list.append(result)

        logger.info(f"Found results for {len(results_list)} drivers")

        # Stream to Kafka
        if results_list:
            # Log a sample of what we're sending
            if results_list:
                logger.info(f"Sample result to be sent to Kafka: {results_list[0]}")

            stream_to_kafka(producer, "race_results", results_list, RESULTS_TOPIC)
        else:
            logger.warning("No race results found")

        return True
    except Exception as e:
        logger.error(f"Error getting race results: {e}")
        import traceback

        logger.error(traceback.format_exc())
        return False


def get_weather_data(session, producer):
    """Get weather data from the session"""
    try:
        event_name = session.event["EventName"]
        logger.info(f"Fetching weather data from {event_name} {session.name}")
        # Get the weather data from the session
        weather_data = []
        if (
            hasattr(session, "weather_data")
            and session.weather_data is not None
            and not session.weather_data.empty
        ):
            weather_df = session.weather_data
            for _, row in weather_df.iterrows():
                weather_record = row.to_dict()
                weather_record["Year"] = session.event.year
                weather_record["GrandPrix"] = event_name
                weather_record["SessionType"] = session.name
                weather_record["DataType"] = "Weather"
                weather_record["RecordId"] = str(uuid.uuid4())
                # Convert specific data types
                for key, value in weather_record.items():
                    if pd.isna(value):
                        weather_record[key] = None
                    elif isinstance(value, pd.Timestamp):
                        weather_record[key] = value.isoformat()
                weather_data.append(weather_record)
        logger.info(f"Found {len(weather_data)} weather records")
        # Stream to Kafka
        if weather_data:
            stream_to_kafka(producer, "weather", weather_data, WEATHER_TOPIC)
        else:
            logger.warning("No weather data found")
        return True
    except Exception as e:
        logger.error(f"Error getting weather data: {e}")
        import traceback

        logger.error(traceback.format_exc())
        return False


def stream_to_kafka(producer, data_type, data, topic):
    total = len(data)
    logger.info(f"Streaming {total} {data_type} records to Kafka topic {topic}...")

    batch_size = 500
    for i in range(0, total, batch_size):
        if not running:
            logger.info("Shutdown signal received. Stopping stream.")
            break

        end = min(i + batch_size, total)
        batch = data[i:end]

        for record in batch:
            try:
                producer.send(topic, value=record)
            except Exception as e:
                logger.error(f"Error sending {data_type} record: {e}")

        producer.flush()
        logger.info(f"Processed {end}/{total} {data_type} records")

        # Add a small delay to prevent overwhelming Kafka
        if end < total:
            time.sleep(0.05)

    logger.info(f"All {data_type} data flushed to Kafka")


import concurrent.futures


def main():
    args = parse_args()
    logger.info(f"Starting producer for {args.year} {args.event} {args.session}")

    # Check if running in prediction mode
    if args.prediction_mode:
        logger.info("Running in prediction mode")
        return process_prediction_data(args)

    try:
        # Load the session
        session = fastf1.get_session(args.year, args.event, args.session)
        session.load()
        logger.info(f"Successfully loaded session data for {args.event} {args.session}")

        # Connect to Kafka
        producer = init_kafka_producer()
        if not producer:
            logger.error("Could not connect to Kafka. Exiting.")
            return 1

        # Process the data in parallel
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
            # Submit all tasks with producer parameter
            lap_future = executor.submit(get_lap_data, session, producer)
            telemetry_future = executor.submit(get_telemetry_data, session, producer)
            position_future = executor.submit(get_position_data, session, producer)
            driver_info_future = executor.submit(get_driver_info, session, producer)
            results_future = executor.submit(get_race_results, session, producer)
            weather_future = executor.submit(get_weather_data, session, producer)

            # Wait for completion
            lap_done = lap_future.result()
            telemetry_done = telemetry_future.result()
            position_done = position_future.result()
            driver_info_done = driver_info_future.result()
            results_done = results_future.result()
            weather_done = weather_future.result()

            logger.info(f"Lap data processing completed: {lap_done}")
            logger.info(f"Telemetry processing completed: {telemetry_done}")
            logger.info(f"Position processing completed: {position_done}")
            logger.info(f"Driver info processing completed: {driver_info_done}")
            logger.info(f"Race results processing completed: {results_done}")
            logger.info(f"Weather data processing completed: {weather_done}")

        producer.close()
        logger.info("Producer completed successfully.")
        return 0

    except Exception as e:
        logger.error(f"Error in producer main function: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
