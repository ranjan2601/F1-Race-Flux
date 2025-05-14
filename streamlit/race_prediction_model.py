import os
import pandas as pd
import numpy as np
import fastf1
import matplotlib.pyplot as plt
import seaborn as sns
from pyspark.ml import Pipeline
from pyspark.ml.feature import (
    OneHotEncoder,
    StandardScaler,
    StringIndexer,
    VectorAssembler,
)
from pyspark.ml.regression import GBTRegressor
from pyspark.sql import SparkSession
from pyspark.ml.evaluation import RegressionEvaluator
import logging
import time
import json
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("RacePredictionModel")

# Create cache directory if it doesn't exist
CACHE_DIR = "/app/predictions/cache"
DATA_DIR = "/app/predictions/data"
RESULTS_DIR = "/app/predictions/results"

# Create directories
for directory in [CACHE_DIR, DATA_DIR, RESULTS_DIR]:
    try:
        os.makedirs(directory, exist_ok=True)
        # Test if directory is writable
        test_file = os.path.join(directory, ".test_write")
        with open(test_file, "w") as f:
            f.write("test")
        os.remove(test_file)
        logger.info(f"Successfully created and verified directory: {directory}")
    except Exception as e:
        logger.error(f"Error creating or accessing directory {directory}: {e}")

# Enable FastF1 cache with error handling
try:
    fastf1.Cache.enable_cache(CACHE_DIR)
    logger.info(f"FastF1 cache enabled at {CACHE_DIR}")
except Exception as e:
    logger.error(f"Failed to enable FastF1 cache: {e}")
    # Try fallback to a temporary directory
    import tempfile

    temp_cache = tempfile.mkdtemp()
    logger.info(f"Attempting to use temporary cache directory: {temp_cache}")
    try:
        fastf1.Cache.enable_cache(temp_cache)
        logger.info(f"FastF1 cache enabled at temporary location: {temp_cache}")
    except Exception as e2:
        logger.error(f"Failed to enable fallback cache: {e2}")
        logger.warning("Running without FastF1 cache - performance will be degraded")

# 2025 driver lineup
DRIVERS_2025 = {
    "McLaren": {"drivers": ["Lando Norris", "Oscar Piastri"]},
    "Ferrari": {"drivers": ["Charles Leclerc", "Lewis Hamilton"]},
    "Red Bull Racing": {"drivers": ["Max Verstappen", "Yuki Tsunoda"]},
    "Mercedes": {"drivers": ["George Russell", "Andrea Kimi Antonelli"]},
    "Aston Martin": {"drivers": ["Fernando Alonso", "Lance Stroll"]},
    "Alpine": {"drivers": ["Pierre Gasly", "Jack Doohan"]},
    "Haas": {"drivers": ["Esteban Ocon", "Oliver Bearman"]},
    "Racing Bulls": {"drivers": ["Isack Hadjar", "Liam Lawson"]},
    "Williams": {"drivers": ["Alexander Albon", "Carlos Sainz"]},
    "Kick Sauber": {"drivers": ["Nico Hülkenberg", "Gabriel Bortoleto"]},
}

# Mapping of abbreviated team names to full names
TEAM_NAME_MAPPING = {
    "McLaren": ["McLaren", "MCL"],
    "Ferrari": ["Ferrari", "FER"],
    "Red Bull Racing": ["Red Bull", "RB", "RBR"],
    "Mercedes": ["Mercedes", "MER"],
    "Aston Martin": ["Aston Martin", "AST", "AM"],
    "Alpine": ["Alpine", "ALP"],
    "Haas": ["Haas", "HAAS"],
    "Racing Bulls": ["RB", "Racing Bulls", "AlphaTauri", "Toro Rosso", "VCARB"],
    "Williams": ["Williams", "WIL"],
    "Kick Sauber": ["Sauber", "Alfa Romeo", "Kick Sauber", "SAU"],
}

# Driver mapping to handle variations in names
DRIVER_MAPPING = {
    "VER": "Max Verstappen",
    "LEC": "Charles Leclerc",
    "NOR": "Lando Norris",
    "HAM": "Lewis Hamilton",
    "RUS": "George Russell",
    "PIA": "Oscar Piastri",
    "SAI": "Carlos Sainz",
    "ALO": "Fernando Alonso",
    "STR": "Lance Stroll",
    "GAS": "Pierre Gasly",
    "TSU": "Yuki Tsunoda",
    "ALB": "Alexander Albon",
    "OCO": "Esteban Ocon",
    "HUL": "Nico Hülkenberg",
    "BOT": "Valtteri Bottas",
    "ZHO": "Zhou Guanyu",
    "SAR": "Logan Sargeant",
    "RIC": "Daniel Ricciardo",
    "MAG": "Kevin Magnussen",
    "LAW": "Liam Lawson",
    "BEA": "Oliver Bearman",
}


def normalize_team_name(team_name):
    """Map various team name formats to a standard name"""
    if not team_name:
        return "Unknown"

    team_name = str(team_name).strip()

    for standard_name, variations in TEAM_NAME_MAPPING.items():
        if any(variation.lower() in team_name.lower() for variation in variations):
            return standard_name

    return team_name


def normalize_driver_name(driver_code_or_name):
    """Normalize driver name from code or partial name"""
    if not driver_code_or_name:
        return "Unknown"

    driver = str(driver_code_or_name).strip()

    # Check if it's a driver code
    if driver.upper() in DRIVER_MAPPING:
        return DRIVER_MAPPING[driver.upper()]

    # Check if it's a full name already
    for full_name in DRIVER_MAPPING.values():
        if driver.lower() in full_name.lower():
            return full_name

    return driver


def get_team_for_driver(driver_name, year=2024):
    """Get team for a driver in a specific year or 2025"""
    normalized_name = normalize_driver_name(driver_name)

    # Check 2025 lineup first
    for team, data in DRIVERS_2025.items():
        if normalized_name in data["drivers"]:
            return team

    # If not found in 2025 lineup, we need to handle this case
    # For simplicity, we'll just return "Unknown"
    return "Unknown"


def fetch_historical_race_data(race_name, years):
    """
    Fetch historical data for model training using FastF1

    Parameters:
    - race_name: Name of the race (e.g., 'Australian Grand Prix')
    - years: List of years to use for training (e.g., [2022, 2023, 2024])

    Returns:
    - Dictionary containing DataFrames for different data types
    """
    logger.info(f"Fetching historical data for {race_name} from years {years}")

    # Initialize data containers
    all_lap_data = []
    all_results_data = []
    all_weather_data = []

    # Find matching race for each year
    for year in years:
        try:
            # Get race schedule for the year
            schedule = fastf1.get_event_schedule(year)

            # Find matching race
            race_event = None
            race_name_lower = race_name.lower()

            for _, event in schedule.iterrows():
                if race_name_lower in event["EventName"].lower():
                    race_event = event
                    break

            if race_event is None:
                logger.warning(f"No matching race found for {race_name} in {year}")
                continue

            # Load the race session
            session = fastf1.get_session(year, race_event["EventName"], "R")
            session.load()

            logger.info(f"Loaded race data for {year} {race_event['EventName']}")

            # Process lap data
            laps_df = session.laps.copy()

            # Add year and race info
            laps_df["Year"] = year
            laps_df["GrandPrix"] = race_event["EventName"]

            # Standardize driver and team names
            laps_df["FullName"] = laps_df["Driver"].apply(normalize_driver_name)
            laps_df["TeamName"] = laps_df["Team"].apply(normalize_team_name)

            # Add to collection
            all_lap_data.append(laps_df)

            # Process results data
            if hasattr(session, "results") and session.results is not None:
                results_df = session.results.copy()

                # Add year and race info
                results_df["Year"] = year
                results_df["GrandPrix"] = race_event["EventName"]

                # Standardize team names and add full names
                results_df["TeamName"] = results_df["TeamName"].apply(
                    normalize_team_name
                )
                results_df["FullName"] = results_df["Abbreviation"].apply(
                    normalize_driver_name
                )

                # Add to collection
                all_results_data.append(results_df)

            # Process weather data
            if hasattr(session, "weather_data") and session.weather_data is not None:
                weather_df = session.weather_data.copy()

                # Add year and race info
                weather_df["Year"] = year
                weather_df["GrandPrix"] = race_event["EventName"]

                # Add to collection
                all_weather_data.append(weather_df)

        except Exception as e:
            logger.error(f"Error processing data for {year}: {e}")

    # Combine all data
    combined_data = {}

    if all_lap_data:
        combined_data["laps"] = pd.concat(all_lap_data, ignore_index=True)
        # Save to file
        safe_filename = os.path.join(
            DATA_DIR, f"{race_name.replace(' ', '_')}_laps.csv"
        )
        combined_data["laps"].to_csv(safe_filename, index=False)

    if all_results_data:
        combined_data["results"] = pd.concat(all_results_data, ignore_index=True)
        # Save to file
        safe_filename = os.path.join(
            DATA_DIR, f"{race_name.replace(' ', '_')}_results.csv"
        )
        combined_data["results"].to_csv(safe_filename, index=False)

    if all_weather_data:
        combined_data["weather"] = pd.concat(all_weather_data, ignore_index=True)
        # Save to file
        safe_filename = os.path.join(
            DATA_DIR, f"{race_name.replace(' ', '_')}_weather.csv"
        )
        combined_data["weather"].to_csv(safe_filename, index=False)

    # Log data summary
    for key, df in combined_data.items():
        logger.info(f"Collected {len(df)} {key} records across {len(years)} years")

    return combined_data


def preprocess_data(data):
    """
    Preprocess the data for model training

    Parameters:
    - data: Dictionary of DataFrames from fetch_historical_race_data

    Returns:
    - DataFrame ready for model training
    """
    logger.info("Preprocessing data for model training")

    if not data or "results" not in data:
        logger.error("No results data available for preprocessing")
        return None

    # Start with race results as the base
    results_df = data["results"].copy()

    # Ensure numeric position
    results_df["Position"] = pd.to_numeric(results_df["Position"], errors="coerce")

    # Calculate average lap times and other metrics by driver
    if "laps" in data and not data["laps"].empty:
        lap_df = data["laps"].copy()

        # Convert lap time to seconds for calculations
        lap_df["LapTimeSeconds"] = lap_df["LapTime"].dt.total_seconds()

        # Aggregate lap data by driver and year
        lap_stats = (
            lap_df.groupby(["FullName", "Year", "GrandPrix"])
            .agg(
                {
                    "LapTimeSeconds": ["mean", "min", "std"],
                    "SpeedST": ["mean", "max"],
                    "IsPersonalBest": "sum",
                    "Stint": "nunique",
                    "LapNumber": "count",
                }
            )
            .reset_index()
        )

        # Flatten multi-level column names
        lap_stats.columns = [
            "_".join(col).strip("_") for col in lap_stats.columns.values
        ]

        # Rename for clarity
        lap_stats = lap_stats.rename(
            columns={
                "FullName_": "FullName",
                "Year_": "Year",
                "GrandPrix_": "GrandPrix",
                "LapTimeSeconds_mean": "AvgLapTime",
                "LapTimeSeconds_min": "BestLapTime",
                "LapTimeSeconds_std": "LapTimeConsistency",
                "SpeedST_mean": "AvgSpeed",
                "SpeedST_max": "MaxSpeed",
                "IsPersonalBest_sum": "PersonalBestCount",
                "Stint_nunique": "PitStopCount",
                "LapNumber_count": "CompletedLaps",
            }
        )

        # Join with results
        results_df = results_df.merge(
            lap_stats, on=["FullName", "Year", "GrandPrix"], how="left"
        )

    # Add weather data
    if "weather" in data and not data["weather"].empty:
        weather_df = data["weather"].copy()

        # Aggregate weather data by race
        weather_stats = (
            weather_df.groupby(["Year", "GrandPrix"])
            .agg(
                {
                    "AirTemp": "mean",
                    "Humidity": "mean",
                    "Pressure": "mean",
                    "Rainfall": lambda x: x.any(),
                    "TrackTemp": "mean",
                    "WindSpeed": "mean",
                }
            )
            .reset_index()
        )

        # Rename for clarity
        weather_stats = weather_stats.rename(
            columns={
                "AirTemp": "AvgAirTemp",
                "Humidity": "AvgHumidity",
                "Pressure": "AvgPressure",
                "Rainfall": "HadRainfall",
                "TrackTemp": "AvgTrackTemp",
                "WindSpeed": "AvgWindSpeed",
            }
        )

        # Join with results
        results_df = results_df.merge(
            weather_stats, on=["Year", "GrandPrix"], how="left"
        )

    # Clean up and prepare the final dataset
    model_df = results_df.copy()

    # Add grid position delta (qualifying to race)
    model_df["GridPositionDelta"] = model_df["GridPosition"] - model_df["Position"]

    # Select and format final features
    feature_columns = [
        "FullName",
        "TeamName",
        "Year",
        "GrandPrix",
        "Position",
        "GridPosition",
        "GridPositionDelta",
    ]

    # Add lap data features if available
    if "AvgLapTime" in model_df.columns:
        feature_columns.extend(
            [
                "AvgLapTime",
                "BestLapTime",
                "LapTimeConsistency",
                "AvgSpeed",
                "MaxSpeed",
                "PersonalBestCount",
                "PitStopCount",
                "CompletedLaps",
            ]
        )

    # Add weather features if available
    if "AvgAirTemp" in model_df.columns:
        feature_columns.extend(
            ["AvgAirTemp", "AvgHumidity", "AvgTrackTemp", "AvgWindSpeed", "HadRainfall"]
        )

    # Select columns that exist
    final_columns = [col for col in feature_columns if col in model_df.columns]
    model_df = model_df[final_columns]

    # Drop rows with missing position (our target variable)
    model_df = model_df.dropna(subset=["Position"])

    # Fill other missing values with medians or modes per team
    numeric_cols = model_df.select_dtypes(include=["number"]).columns
    for col in numeric_cols:
        if col in model_df.columns and model_df[col].isna().any():
            # Use team-specific medians where possible
            team_medians = model_df.groupby("TeamName")[col].transform("median")
            global_median = model_df[col].median()
            model_df[col] = model_df[col].fillna(team_medians).fillna(global_median)

    # Fill any remaining NaNs
    model_df = model_df.fillna(0)

    return model_df


def build_model(training_data):
    """
    Build and train a Gradient Boosting model using PySpark MLlib

    Parameters:
    - training_data: Preprocessed DataFrame for training

    Returns:
    - Trained model and preprocessing pipeline
    """
    logger.info("Building and training prediction model with PySpark MLlib")

    if training_data is None or training_data.empty:
        logger.error("No training data available")
        return None, None

    # Initialize Spark session with simplified configuration for container environment
    try:
        spark = (
            SparkSession.builder.appName("F1RacePrediction")
            .master("local[*]")
            .config("spark.driver.memory", "1g")
            .config("spark.executor.memory", "1g")
            .config("spark.ui.enabled", "false")
            .config("spark.sql.execution.arrow.pyspark.enabled", "false")
            .config("spark.driver.bindAddress", "127.0.0.1")
            .getOrCreate()
        )

        logger.info("Successfully created Spark session")

        # Preprocess data to ensure consistent types for Spark
        preprocessed_data = training_data.copy()

        # Special handling for HadRainfall column which has caused issues
        if "HadRainfall" in preprocessed_data.columns:
            logger.info("Converting HadRainfall to integer type")
            if pd.api.types.is_bool_dtype(preprocessed_data["HadRainfall"]):
                preprocessed_data["HadRainfall"] = preprocessed_data[
                    "HadRainfall"
                ].astype(int)
            else:
                # If it's not already boolean, convert through string to int
                preprocessed_data["HadRainfall"] = preprocessed_data[
                    "HadRainfall"
                ].astype(str)
                preprocessed_data["HadRainfall"] = preprocessed_data["HadRainfall"].map(
                    {"True": 1, "False": 0, "true": 1, "false": 0, "1": 1, "0": 0}
                )
                preprocessed_data["HadRainfall"] = (
                    preprocessed_data["HadRainfall"].fillna(0).astype(int)
                )

            # Double check the conversion
            logger.info(
                f"HadRainfall column type is now: {preprocessed_data['HadRainfall'].dtype}"
            )

        # Convert boolean columns to integer (0/1) to avoid type conflicts
        for col in preprocessed_data.columns:
            if pd.api.types.is_bool_dtype(preprocessed_data[col]):
                logger.info(f"Converting boolean column {col} to integer")
                preprocessed_data[col] = preprocessed_data[col].astype(int)
            elif preprocessed_data[col].dtype == "object":
                # Ensure all string columns are properly formatted
                preprocessed_data[col] = preprocessed_data[col].astype(str)
            elif pd.api.types.is_float_dtype(preprocessed_data[col]):
                # Handle NaNs in float columns
                preprocessed_data[col] = preprocessed_data[col].fillna(0.0)
            elif pd.api.types.is_integer_dtype(preprocessed_data[col]):
                # Handle NaNs in integer columns
                preprocessed_data[col] = preprocessed_data[col].fillna(0)

        # Log the data types of all columns for debugging
        logger.info("Data types after preprocessing:")
        for col, dtype in preprocessed_data.dtypes.items():
            logger.info(f"Column: {col}, Type: {dtype}")

        # Convert pandas DataFrame to Spark DataFrame
        try:
            logger.info("Converting pandas DataFrame to Spark DataFrame")
            spark_df = spark.createDataFrame(preprocessed_data)
            logger.info(
                f"Successfully created Spark DataFrame with {spark_df.count()} rows"
            )

            # Log Spark DataFrame schema for debugging
            logger.info("Spark DataFrame schema:")
            for field in spark_df.schema.fields:
                logger.info(f"Column: {field.name}, Type: {field.dataType}")

        except Exception as e:
            logger.error(f"Error converting DataFrame: {e}")
            # Fallback: try schema-based conversion
            try:
                from pyspark.sql.types import (
                    StructType,
                    StructField,
                    StringType,
                    DoubleType,
                    IntegerType,
                )

                # Create schema manually
                logger.info("Attempting schema-based conversion")
                fields = []
                for col_name, dtype in preprocessed_data.dtypes.items():
                    if col_name == "HadRainfall":
                        # Ensure HadRainfall is always IntegerType
                        fields.append(StructField(col_name, IntegerType(), True))
                    elif pd.api.types.is_float_dtype(dtype):
                        fields.append(StructField(col_name, DoubleType(), True))
                    elif pd.api.types.is_integer_dtype(dtype):
                        fields.append(StructField(col_name, IntegerType(), True))
                    else:
                        fields.append(StructField(col_name, StringType(), True))

                schema = StructType(fields)
                spark_df = spark.createDataFrame(
                    preprocessed_data.values.tolist(), schema=schema
                )
                spark_df = spark_df.toDF(*preprocessed_data.columns)
                logger.info(
                    f"Successfully created Spark DataFrame with schema, {spark_df.count()} rows"
                )

                # Log Spark DataFrame schema for debugging
                logger.info("Spark DataFrame schema (manual):")
                for field in spark_df.schema.fields:
                    logger.info(f"Column: {field.name}, Type: {field.dataType}")

            except Exception as e2:
                logger.error(f"Schema-based conversion also failed: {e2}")
                raise RuntimeError(
                    "Could not convert pandas DataFrame to Spark DataFrame"
                ) from e

        # Define features and target
        target_col = "Position"

        # Identify categorical and numerical columns
        categorical_features = ["FullName", "TeamName", "GrandPrix"]
        categorical_features = [
            f for f in categorical_features if f in preprocessed_data.columns
        ]

        numeric_features = preprocessed_data.select_dtypes(
            include=["number"]
        ).columns.tolist()
        numeric_features = [f for f in numeric_features if f != target_col]

        logger.info(f"Using categorical features: {categorical_features}")
        logger.info(f"Using numeric features: {numeric_features}")

        # Create preprocessing stages
        # 1. String indexers for categorical features
        indexers = [
            StringIndexer(inputCol=col, outputCol=f"{col}_idx", handleInvalid="keep")
            for col in categorical_features
        ]

        # 2. One-hot encoding for indexed categorical features
        encoders = [
            OneHotEncoder(inputCol=f"{col}_idx", outputCol=f"{col}_vec")
            for col in categorical_features
        ]

        # 3. Vector assembler for numerical features
        numeric_assembler = VectorAssembler(
            inputCols=numeric_features,
            outputCol="numeric_features",
            handleInvalid="keep",
        )

        # 4. Standard scaler for numerical features
        scaler = StandardScaler(
            inputCol="numeric_features",
            outputCol="scaled_numeric_features",
            withStd=True,
            withMean=True,
        )

        # 5. Assemble all features together
        categorical_vec_cols = [f"{col}_vec" for col in categorical_features]
        assembler = VectorAssembler(
            inputCols=categorical_vec_cols + ["scaled_numeric_features"],
            outputCol="features",
            handleInvalid="keep",
        )

        # 6. Create the gradient boosting regressor with reduced complexity for container
        gbt = GBTRegressor(
            featuresCol="features",
            labelCol=target_col,
            maxIter=50,
            maxDepth=3,
            stepSize=0.1,
        )

        # Create the pipeline
        pipeline = Pipeline(
            stages=indexers + encoders + [numeric_assembler, scaler, assembler, gbt]
        )

        # Split data into training and test sets
        train_df, test_df = spark_df.randomSplit([0.8, 0.2], seed=42)

        # Train the model
        logger.info("Training the PySpark GBT model...")
        model = pipeline.fit(train_df)

        # Evaluate model
        logger.info("Evaluating the model...")
        predictions = model.transform(test_df)

        evaluator = RegressionEvaluator(
            labelCol=target_col, predictionCol="prediction", metricName="r2"
        )

        r2 = evaluator.evaluate(predictions)
        rmse = evaluator.setMetricName("rmse").evaluate(predictions)

        logger.info(f"Model training completed with R² score: {r2:.3f}")
        logger.info(f"RMSE: {rmse:.3f}")

        # Store the Spark session with the model for predictions
        # We return the full pipeline and the Spark session
        return model, spark

    except Exception as e:
        logger.error(f"Error in PySpark model building: {e}")
        import traceback

        logger.error(traceback.format_exc())
        try:
            if "spark" in locals() and spark is not None:
                spark.stop()
        except:
            pass
        return None, None


def create_2025_driver_dataset(training_data):
    """
    Create a dataset for 2025 drivers based on historical data

    Parameters:
    - training_data: Preprocessed historical data

    Returns:
    - DataFrame with 2025 driver predictions
    """
    logger.info("Creating 2025 driver dataset")

    # Start with the most recent year's data
    latest_year = training_data["Year"].max()
    race_name = training_data["GrandPrix"].iloc[0]

    latest_data = training_data[training_data["Year"] == latest_year].copy()

    # Create a new dataset for 2025 predictions
    prediction_rows = []

    # Process each team and its drivers from our 2025 lineup dictionary
    for team_name, team_info in DRIVERS_2025.items():
        for driver_name in team_info["drivers"]:

            # Case 1: Driver exists in historical data
            driver_historical = training_data[training_data["FullName"] == driver_name]

            if not driver_historical.empty:
                # Use the driver's most recent data
                driver_recent = (
                    driver_historical.sort_values("Year", ascending=False)
                    .iloc[0]
                    .to_dict()
                )

                # Update for 2025
                driver_recent["Year"] = 2025
                driver_recent["TeamName"] = team_name

                prediction_rows.append(driver_recent)
                continue

            # Case 2: Driver's teammate exists in historical data
            teammate = None
            for d in team_info["drivers"]:
                if (
                    d != driver_name
                    and training_data[training_data["FullName"] == d].shape[0] > 0
                ):
                    teammate = d
                    break

            if teammate:
                teammate_data = (
                    training_data[training_data["FullName"] == teammate]
                    .sort_values("Year", ascending=False)
                    .iloc[0]
                    .to_dict()
                )

                # Modify teammate data for new driver
                # New drivers typically perform worse than experienced teammates
                teammate_data["FullName"] = driver_name
                teammate_data["Year"] = 2025
                teammate_data["TeamName"] = team_name

                # Adjust performance metrics (slightly worse than teammate)
                if "AvgLapTime" in teammate_data:
                    teammate_data["AvgLapTime"] *= 1.01  # 1% slower

                if "BestLapTime" in teammate_data:
                    teammate_data["BestLapTime"] *= 1.01  # 1% slower

                if "MaxSpeed" in teammate_data:
                    teammate_data["MaxSpeed"] *= 0.99  # 1% slower

                prediction_rows.append(teammate_data)
                continue

            # Case 3: No historical data for driver or teammate
            # Use team average or create synthetic data
            team_data = training_data[training_data["TeamName"] == team_name]

            if not team_data.empty:
                # Use team average
                team_avg = team_data.mean(numeric_only=True).to_dict()
                team_mode = team_data.mode().iloc[0]

                driver_row = {
                    "FullName": driver_name,
                    "TeamName": team_name,
                    "Year": 2025,
                    "GrandPrix": race_name,
                    "GridPosition": team_avg.get(
                        "GridPosition", 10
                    ),  # Reasonable default
                }

                # Add numeric features from team average
                for col, val in team_avg.items():
                    if col not in driver_row:
                        driver_row[col] = val

                prediction_rows.append(driver_row)
                continue

            # Case 4: Completely new team with no data
            # Create sensible defaults based on team's presumed performance
            # This is very speculative
            team_performance = {
                "McLaren": 1.5,  # Top team
                "Ferrari": 1.8,
                "Red Bull Racing": 1.2,  # Best team
                "Mercedes": 2.2,
                "Aston Martin": 4.0,
                "Alpine": 6.0,
                "Williams": 8.0,
                "Racing Bulls": 7.0,
                "Haas": 9.0,
                "Kick Sauber": 10.0,  # Bottom team
            }

            baseline_position = team_performance.get(team_name, 10)

            # Create a reasonable default row
            driver_row = {
                "FullName": driver_name,
                "TeamName": team_name,
                "Year": 2025,
                "GrandPrix": race_name,
                "GridPosition": baseline_position,
                "GridPositionDelta": 0,
            }

            # Add typical values based on grid position
            if training_data.shape[0] > 0:
                # Get average values by position
                position_metrics = training_data.groupby("GridPosition").mean(
                    numeric_only=True
                )

                # Find closest position
                closest_position = min(
                    position_metrics.index, key=lambda x: abs(x - baseline_position)
                )
                position_avg = position_metrics.loc[closest_position].to_dict()

                # Apply these averages to the driver
                for col, val in position_avg.items():
                    if col not in driver_row:
                        driver_row[col] = val

            prediction_rows.append(driver_row)

    # Create DataFrame from all prediction rows
    predictions_df = pd.DataFrame(prediction_rows)

    # Ensure we have all the columns from the training data
    for col in training_data.columns:
        if col not in predictions_df.columns:
            if col == "Position":
                continue
            # Add with default values
            if training_data[col].dtype == "object":
                predictions_df[col] = "Unknown"
            else:
                predictions_df[col] = 0

    logger.info(f"Created prediction dataset with {len(predictions_df)} 2025 drivers")

    return predictions_df


def calculate_weather_impact(row):
    """Calculate the impact of weather on lap times"""
    impact = 1.0  # baseline multiplier

    # Rainfall slows cars down
    if row.get("HadRainfall", False):
        impact *= 1.05  # 5% slower in rain

    # Temperature impacts
    air_temp = row.get("AvgAirTemp", 25.0)
    track_temp = row.get("AvgTrackTemp", 30.0)

    # Very hot conditions can degrade tires faster
    if track_temp > 40:
        impact *= 1.02  # 2% slower in very hot conditions
    # Cold track reduces grip
    elif track_temp < 20:
        impact *= 1.015  # 1.5% slower in cold conditions

    # Wind speed impacts
    wind_speed = row.get("AvgWindSpeed", 10.0)
    if wind_speed > 20:
        impact *= 1.01  # 1% slower in high winds

    return impact


def calculate_race_details(predictions_df, race_name, avg_lap_time=90.0, laps=58):
    """
    Calculate estimated race times and add tire degradation factors

    Parameters:
    - predictions_df: DataFrame with predictions
    - race_name: Name of the race
    - avg_lap_time: Average lap time in seconds (default 90s)
    - laps: Number of laps in the race (default 58)

    Returns:
    - DataFrame with added race details
    """
    # Race-specific parameters
    race_parameters = {
        "Australian Grand Prix": {
            "laps": 58,
            "avg_lap_time": 85.0,
            "tire_deg_factor": 0.10,
        },
        "Monaco Grand Prix": {
            "laps": 78,
            "avg_lap_time": 75.0,
            "tire_deg_factor": 0.05,
        },
        "British Grand Prix": {
            "laps": 52,
            "avg_lap_time": 87.0,
            "tire_deg_factor": 0.12,
        },
        "Italian Grand Prix": {
            "laps": 53,
            "avg_lap_time": 82.0,
            "tire_deg_factor": 0.08,
        },
        "Singapore Grand Prix": {
            "laps": 62,
            "avg_lap_time": 95.0,
            "tire_deg_factor": 0.15,
        },
    }

    # Get race-specific parameters or use defaults
    params = race_parameters.get(
        race_name, {"laps": laps, "avg_lap_time": avg_lap_time, "tire_deg_factor": 0.10}
    )

    # Add race time estimates
    enhanced_df = predictions_df.copy()

    # Calculate base time and add randomness for realism
    for idx, row in enhanced_df.iterrows():
        # Base race time calculation using predicted position
        position_penalty = (row["PredictedPosition"] - 1) * 0.3  # 0.3s per position

        # Weather impact (random for demo, would be based on actual prediction in a real model)
        weather_impact = 1.0
        if row.get("AvgAirTemp", 25) > 30:
            weather_impact = 1.02  # Hot conditions
        elif row.get("HadRainfall", False):
            weather_impact = 1.08  # Rainy conditions

        # Tire degradation impact (increases with race duration)
        tire_factor = 1.0 + (params["tire_deg_factor"] * (position_penalty / 10))

        # Calculate total race time
        lap_time = (
            params["avg_lap_time"]
            * (1 + position_penalty / 100)
            * weather_impact
            * tire_factor
        )
        race_time_seconds = lap_time * params["laps"]

        # Add a small random factor for realistic variability
        race_time_seconds *= 1 + (np.random.random() - 0.5) * 0.02

        # Convert to hours:minutes:seconds format
        hours = int(race_time_seconds // 3600)
        minutes = int((race_time_seconds % 3600) // 60)
        seconds = race_time_seconds % 60

        # Store the values
        enhanced_df.at[idx, "EstimatedLapTime"] = lap_time
        enhanced_df.at[idx, "EstimatedRaceTime"] = (
            f"{hours:01d}:{minutes:02d}:{seconds:06.3f}"
        )
        enhanced_df.at[idx, "RaceTimeSeconds"] = race_time_seconds
        enhanced_df.at[idx, "TireDegradation"] = tire_factor
        enhanced_df.at[idx, "WeatherImpact"] = weather_impact
        enhanced_df.at[idx, "TotalLaps"] = params["laps"]

    # Sort by predicted position again after modifications
    enhanced_df = enhanced_df.sort_values("PredictedPosition")

    # Calculate gaps to leader
    if len(enhanced_df) > 0:
        leader_time = enhanced_df.iloc[0]["RaceTimeSeconds"]
        enhanced_df["GapToLeader"] = enhanced_df["RaceTimeSeconds"] - leader_time

        # Format gap to leader
        def format_gap(seconds):
            if seconds < 0.001:  # Leader
                return "Leader"
            elif seconds > 60:  # More than a minute
                minutes = int(seconds // 60)
                secs = seconds % 60
                return f"+{minutes}m {secs:.3f}s"
            else:
                return f"+{seconds:.3f}s"

        enhanced_df["Gap"] = enhanced_df["GapToLeader"].apply(format_gap)

    return enhanced_df


def predict_race_outcome(model, spark, training_data, prediction_data):
    """
    Predict race outcomes for 2025 using PySpark model

    Parameters:
    - model: Trained PySpark pipeline model
    - spark: SparkSession
    - training_data: Historical data used for training
    - prediction_data: Data for 2025 drivers

    Returns:
    - DataFrame with predictions
    """
    logger.info("Predicting 2025 race outcome using PySpark model")

    if (
        model is None
        or prediction_data is None
        or prediction_data.empty
        or spark is None
    ):
        logger.error("No model, Spark session, or prediction data available")
        return None

    try:
        # First preprocess data to ensure consistent types for Spark
        preprocessed_data = prediction_data.copy()

        # Get the schema of the trained model's input to ensure consistency
        # This helps us identify any potential type mismatches
        logger.info("Analyzing model input schema")
        try:
            # Get the structure of the trained pipeline's first stage input
            model_input_schema = model.stages[0]._call_java(
                "transformSchema", model.stages[0]._input_kwargs["inputCol"]
            )
            logger.info(
                f"Model input schema detected for {model.stages[0]._input_kwargs['inputCol']}"
            )
        except:
            logger.info(
                "Could not retrieve model schema, continuing with standard preprocessing"
            )

        # Special handling for HadRainfall column which has caused issues
        if "HadRainfall" in preprocessed_data.columns:
            logger.info("Converting HadRainfall to integer type")
            if pd.api.types.is_bool_dtype(preprocessed_data["HadRainfall"]):
                preprocessed_data["HadRainfall"] = preprocessed_data[
                    "HadRainfall"
                ].astype(int)
            else:
                # If it's not already boolean, convert through string to int
                preprocessed_data["HadRainfall"] = preprocessed_data[
                    "HadRainfall"
                ].astype(str)
                preprocessed_data["HadRainfall"] = preprocessed_data["HadRainfall"].map(
                    {"True": 1, "False": 0, "true": 1, "false": 0, "1": 1, "0": 0}
                )
                preprocessed_data["HadRainfall"] = (
                    preprocessed_data["HadRainfall"].fillna(0).astype(int)
                )

            # Double check the conversion
            logger.info(
                f"HadRainfall column type is now: {preprocessed_data['HadRainfall'].dtype}"
            )

        # Convert boolean columns to integer (0/1) to avoid type conflicts
        for col in preprocessed_data.columns:
            if pd.api.types.is_bool_dtype(preprocessed_data[col]):
                logger.info(f"Converting boolean column {col} to integer")
                preprocessed_data[col] = preprocessed_data[col].astype(int)
            elif preprocessed_data[col].dtype == "object":
                # Ensure all string columns are properly formatted
                preprocessed_data[col] = preprocessed_data[col].astype(str)
            elif pd.api.types.is_float_dtype(preprocessed_data[col]):
                # Handle NaNs in float columns
                preprocessed_data[col] = preprocessed_data[col].fillna(0.0)
            elif pd.api.types.is_integer_dtype(preprocessed_data[col]):
                # Handle NaNs in integer columns
                preprocessed_data[col] = preprocessed_data[col].fillna(0)

        # Log the data types of all columns for debugging
        logger.info("Data types after preprocessing:")
        for col, dtype in preprocessed_data.dtypes.items():
            logger.info(f"Column: {col}, Type: {dtype}")

        # Convert pandas DataFrame to Spark DataFrame with better error handling
        logger.info("Converting prediction data to Spark DataFrame")
        try:
            # Convert to Spark DataFrame
            prediction_spark_df = spark.createDataFrame(preprocessed_data)
            logger.info(
                f"Successfully created Spark DataFrame with {prediction_spark_df.count()} rows"
            )

            # Log Spark DataFrame schema for debugging
            logger.info("Spark DataFrame schema:")
            for field in prediction_spark_df.schema.fields:
                logger.info(f"Column: {field.name}, Type: {field.dataType}")

        except Exception as e:
            logger.error(f"Error converting to Spark DataFrame: {e}")
            # Fallback: try schema-based conversion
            try:
                from pyspark.sql.types import (
                    StructType,
                    StructField,
                    StringType,
                    DoubleType,
                    IntegerType,
                )

                # Create schema manually
                logger.info("Attempting schema-based conversion")
                fields = []
                for col_name, dtype in preprocessed_data.dtypes.items():
                    if col_name == "HadRainfall":
                        # Ensure HadRainfall is always IntegerType
                        fields.append(StructField(col_name, IntegerType(), True))
                    elif pd.api.types.is_float_dtype(dtype):
                        fields.append(StructField(col_name, DoubleType(), True))
                    elif pd.api.types.is_integer_dtype(dtype):
                        fields.append(StructField(col_name, IntegerType(), True))
                    else:
                        fields.append(StructField(col_name, StringType(), True))

                schema = StructType(fields)
                prediction_spark_df = spark.createDataFrame(
                    preprocessed_data.values.tolist(), schema=schema
                )
                prediction_spark_df = prediction_spark_df.toDF(
                    *preprocessed_data.columns
                )
                logger.info(
                    f"Successfully created Spark DataFrame with schema, {prediction_spark_df.count()} rows"
                )

                # Log Spark DataFrame schema for debugging
                logger.info("Spark DataFrame schema (manual):")
                for field in prediction_spark_df.schema.fields:
                    logger.info(f"Column: {field.name}, Type: {field.dataType}")

            except Exception as e2:
                logger.error(f"Schema-based conversion also failed: {e2}")
                raise RuntimeError(
                    "Could not convert pandas DataFrame to Spark DataFrame"
                ) from e

        # Make predictions using the PySpark pipeline
        logger.info("Running predictions through PySpark model")
        predictions_spark = model.transform(prediction_spark_df)

        # Select relevant columns and convert back to pandas
        # We need to select original columns plus the prediction column
        logger.info("Converting predictions back to pandas DataFrame")
        columns_to_select = prediction_data.columns.tolist() + ["prediction"]
        predictions_pd = predictions_spark.select(*columns_to_select).toPandas()

        # Rename prediction column to match the rest of the code
        results = predictions_pd.rename(columns={"prediction": "PredictedPosition"})

        # Clean up predicted positions (ensure they're rounded and unique)
        results["PredictedPosition"] = results["PredictedPosition"].round(1)

        # Sort by predicted position
        results = results.sort_values("PredictedPosition")

        # Add position change (grid to predicted)
        if "GridPosition" in results.columns:
            results["PositionChange"] = (
                results["GridPosition"] - results["PredictedPosition"]
            )

        # Select relevant columns for display
        display_cols = [
            "FullName",
            "TeamName",
            "PredictedPosition",
            "GridPosition",
            "PositionChange",
            "Year",
            "GrandPrix",
        ]

        # Add weather columns if available
        weather_cols = [
            "AvgAirTemp",
            "AvgTrackTemp",
            "AvgHumidity",
            "AvgWindSpeed",
            "HadRainfall",
        ]
        for col in weather_cols:
            if col in results.columns:
                display_cols.append(col)

        # Keep only columns that exist
        final_cols = [col for col in display_cols if col in results.columns]

        # Create a DataFrame with the selected columns
        final_predictions = results[final_cols].reset_index(drop=True)

        # Calculate weather impact for each driver
        if "AvgAirTemp" in final_predictions.columns:
            final_predictions["WeatherImpact"] = final_predictions.apply(
                calculate_weather_impact, axis=1
            )

        # Add race details like estimated times and tire degradation
        grand_prix = (
            final_predictions["GrandPrix"].iloc[0]
            if not final_predictions.empty
            else "Unknown Grand Prix"
        )
        detailed_predictions = calculate_race_details(final_predictions, grand_prix)

        return detailed_predictions

    except Exception as e:
        logger.error(f"Error in PySpark prediction: {e}")
        import traceback

        logger.error(traceback.format_exc())
        return None


def save_prediction_results(predictions_df, race_name):
    """
    Save prediction results to file

    Parameters:
    - predictions_df: DataFrame with predictions
    - race_name: Name of the race
    """
    if predictions_df is None or predictions_df.empty:
        logger.error("No predictions to save")
        return

    # Generate filename with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_race_name = race_name.replace(" ", "_").replace("/", "_")

    # Save to CSV
    csv_filename = os.path.join(RESULTS_DIR, f"{safe_race_name}_{timestamp}.csv")
    try:
        predictions_df.to_csv(csv_filename, index=False)
        logger.info(f"Saved prediction results to {csv_filename}")
    except Exception as e:
        logger.error(f"Error saving CSV file: {e}")

    # Also save as JSON for easy loading
    json_filename = os.path.join(RESULTS_DIR, f"{safe_race_name}_{timestamp}.json")

    # Convert to JSON-serializable format
    json_data = {
        "race": race_name,
        "timestamp": timestamp,
        "predictions": predictions_df.to_dict(orient="records"),
    }

    try:
        with open(json_filename, "w") as f:
            json.dump(json_data, f, default=str)
        logger.info(f"Saved prediction results to {json_filename}")
    except Exception as e:
        logger.error(f"Error saving JSON file: {e}")


def run_prediction_model(race_name, source_years_str="2022,2023,2024"):
    """
    Main function to run the prediction model

    Parameters:
    - race_name: Name of the race to predict
    - source_years_str: Comma-separated string of years to use for training

    Returns:
    - DataFrame with predictions
    """
    logger.info(
        f"Starting prediction model for {race_name} using data from {source_years_str}"
    )

    # Parse years
    source_years = [int(y.strip()) for y in source_years_str.split(",")]

    # Variable to store SparkSession for cleanup
    spark = None

    try:
        # 1. Fetch historical race data
        logger.info("Step 1: Fetching historical race data...")
        historical_data = fetch_historical_race_data(race_name, source_years)

        if not historical_data or all(df.empty for df in historical_data.values()):
            logger.error(f"Could not find historical data for {race_name}")
            return None

        # Log the data we found
        for key, df in historical_data.items():
            logger.info(f"Found {len(df)} {key} records for {race_name}")

        # 2. Preprocess the data
        logger.info("Step 2: Preprocessing historical data...")
        processed_data = preprocess_data(historical_data)

        if processed_data is None or processed_data.empty:
            logger.error("Failed to preprocess data")
            return None

        logger.info(
            f"Preprocessed data shape: {processed_data.shape}, columns: {processed_data.columns.tolist()}"
        )

        # 3. Build and train the model
        logger.info("Step 3: Building and training the model...")
        model, spark = build_model(processed_data)

        if model is None:
            logger.error("Failed to build model")
            return None

        # 4. Create dataset for 2025 drivers
        logger.info("Step 4: Creating 2025 driver dataset...")
        try:
            prediction_data = create_2025_driver_dataset(processed_data)

            if prediction_data is None or prediction_data.empty:
                logger.error("Failed to create 2025 driver dataset")
                return None

            logger.info(
                f"Created prediction dataset with shape: {prediction_data.shape}"
            )

        except Exception as e:
            logger.error(f"Error creating 2025 driver dataset: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return None

        # 5. Make predictions
        logger.info("Step 5: Making predictions...")
        predictions = predict_race_outcome(
            model, spark, processed_data, prediction_data
        )

        if predictions is None or predictions.empty:
            logger.error("Failed to generate predictions")
            return None

        logger.info(f"Generated predictions for {len(predictions)} drivers")

        # 6. Save prediction results
        logger.info("Step 6: Saving prediction results...")
        save_prediction_results(predictions, race_name)

        logger.info("Prediction process completed successfully")
        return predictions

    except Exception as e:
        logger.error(f"Error in prediction model: {e}")
        import traceback

        logger.error(traceback.format_exc())
        return None

    finally:
        # Clean up Spark session if it was created
        if spark is not None:
            try:
                logger.info("Stopping Spark session")
                spark.stop()
            except:
                pass
