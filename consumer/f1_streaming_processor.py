from pyspark.sql import SparkSession
from pyspark.sql.functions import (
    col,
    when,
    lit,
    regexp_replace,
    from_json,
    sqrt,
    pow,
    lag,
    udf,
)
from pyspark.sql.types import (
    StructType,
    StructField,
    StringType,
    IntegerType,
    BooleanType,
    DoubleType,
    TimestampType,
)
from pyspark.sql.window import Window
import logging
from pymongo import MongoClient

# Set up logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("F1SparkProcessor")

# Create a Spark session with MongoDB connector and optimized configurations
spark = (
    SparkSession.builder.appName("F1DataProcessing")
    .master("local[*]")
    .config("spark.mongodb.connection.uri", "mongodb://mongodb:27017")
    .config("spark.mongodb.database", "f1db")
    .config(
        "spark.jars.packages",
        "org.apache.spark:spark-sql-kafka-0-10_2.12:3.3.0,"
        "org.mongodb:mongodb-driver-sync:4.7.2,"
        "org.mongodb.spark:mongo-spark-connector_2.12:10.4.1",
    )
    .config("spark.executor.memory", "3g")
    .config("spark.driver.memory", "3g")
    .config("spark.memory.offHeap.enabled", "true")
    .config("spark.memory.offHeap.size", "2g")
    .config("spark.sql.shuffle.partitions", "8")
    .config("spark.default.parallelism", "8")
    .config("spark.streaming.kafka.consumer.poll.ms", "512")
    .config("spark.mongodb.output.batchSize", "4096")
    .config("spark.streaming.kafka.maxRatePerTrigger", "50000")
    .config("spark.cleaner.periodicGC.interval", "30s")
    .config("spark.serializer", "org.apache.spark.serializer.KryoSerializer")
    .config("spark.kryo.registrationRequired", "false")
    .config("spark.kryoserializer.buffer.max", "512m")
    .config("spark.streaming.backpressure.enabled", "true")
    .config("spark.locality.wait", "0s")
    .getOrCreate()
)
logger.info("Spark session created successfully with optimized settings")

# Define schema for lap data
lap_schema = StructType(
    [
        StructField("Time", StringType(), True),
        StructField("Driver", StringType(), True),
        StructField("DriverNumber", StringType(), True),
        StructField("LapTime", StringType(), True),
        StructField("LapNumber", DoubleType(), True),
        StructField("Stint", DoubleType(), True),
        StructField("PitOutTime", StringType(), True),
        StructField("PitInTime", StringType(), True),
        StructField("Sector1Time", StringType(), True),
        StructField("Sector2Time", StringType(), True),
        StructField("Sector3Time", StringType(), True),
        StructField("Sector1SessionTime", StringType(), True),
        StructField("Sector2SessionTime", StringType(), True),
        StructField("Sector3SessionTime", StringType(), True),
        StructField("SpeedI1", DoubleType(), True),
        StructField("SpeedI2", DoubleType(), True),
        StructField("SpeedFL", DoubleType(), True),
        StructField("SpeedST", DoubleType(), True),
        StructField("IsPersonalBest", BooleanType(), True),
        StructField("Compound", StringType(), True),
        StructField("TyreLife", DoubleType(), True),
        StructField("FreshTyre", BooleanType(), True),
        StructField("Team", StringType(), True),
        StructField("LapStartTime", StringType(), True),
        StructField("LapStartDate", TimestampType(), True),
        StructField("TrackStatus", StringType(), True),
        StructField("Position", DoubleType(), True),
        StructField("Deleted", BooleanType(), True),
        StructField("DeletedReason", StringType(), True),
        StructField("FastF1Generated", BooleanType(), True),
        StructField("IsAccurate", BooleanType(), True),
        StructField("Year", IntegerType(), True),
        StructField("GrandPrix", StringType(), True),
        StructField("SessionType", StringType(), True),
        StructField("IsPrediction", BooleanType(), True),
        StructField("SourceYear", IntegerType(), True),
        StructField("SourceEvent", StringType(), True),
    ]
)

# Define schema for telemetry data
telemetry_schema = StructType(
    [
        StructField("Time", StringType(), True),
        StructField("Date", TimestampType(), True),
        StructField("Driver", StringType(), True),
        StructField("RPM", DoubleType(), True),
        StructField("Speed", DoubleType(), True),
        StructField("nGear", IntegerType(), True),
        StructField("Throttle", DoubleType(), True),
        StructField("Brake", DoubleType(), True),
        StructField("DRS", IntegerType(), True),
        StructField("Year", IntegerType(), True),
        StructField("GrandPrix", StringType(), True),
        StructField("SessionType", StringType(), True),
        StructField("DataType", StringType(), True),
        StructField("RecordId", StringType(), True),
        StructField("LapNumber", DoubleType(), True),
        StructField("IsPrediction", BooleanType(), True),
        StructField("SourceYear", IntegerType(), True),
        StructField("SourceEvent", StringType(), True),
    ]
)

# Define schema for position data
position_schema = StructType(
    [
        StructField("Time", StringType(), True),
        StructField("Date", TimestampType(), True),
        StructField("Driver", StringType(), True),
        StructField("X", DoubleType(), True),
        StructField("Y", DoubleType(), True),
        StructField("Z", DoubleType(), True),
        StructField("Status", StringType(), True),
        StructField("Year", IntegerType(), True),
        StructField("GrandPrix", StringType(), True),
        StructField("SessionType", StringType(), True),
        StructField("DataType", StringType(), True),
        StructField("RecordId", StringType(), True),
        StructField("LapNumber", DoubleType(), True),
        StructField("IsPrediction", BooleanType(), True),
        StructField("SourceYear", IntegerType(), True),
        StructField("SourceEvent", StringType(), True),
    ]
)

# Define schema for driver info data
driver_info_schema = StructType(
    [
        StructField("Driver", StringType(), True),
        StructField("DriverNumber", StringType(), True),
        StructField("FullName", StringType(), True),
        StructField("Abbreviation", StringType(), True),
        StructField("TeamName", StringType(), True),
        StructField("Nationality", StringType(), True),
        StructField("Year", IntegerType(), True),
        StructField("GrandPrix", StringType(), True),
        StructField("SessionType", StringType(), True),
        StructField("DataType", StringType(), True),
        StructField("RecordId", StringType(), True),
        StructField("IsPrediction", BooleanType(), True),
        StructField("SourceYear", IntegerType(), True),
        StructField("SourceEvent", StringType(), True),
    ]
)

# Define schema for race results data

results_schema = StructType(
    [
        StructField("Driver", StringType(), True),
        StructField("DriverNumber", StringType(), True),
        StructField("Position", DoubleType(), True),
        StructField("ClassifiedPosition", StringType(), True),
        StructField("GridPosition", DoubleType(), True),
        StructField("Q1", StringType(), True),
        StructField("Q2", StringType(), True),
        StructField("Q3", StringType(), True),
        StructField("Time", StringType(), True),
        StructField("Status", StringType(), True),
        StructField("Points", DoubleType(), True),
        StructField("TeamName", StringType(), True),
        StructField("Year", IntegerType(), True),
        StructField("GrandPrix", StringType(), True),
        StructField("SessionType", StringType(), True),
        StructField("DataType", StringType(), True),
        StructField("RecordId", StringType(), True),
        StructField("IsPrediction", BooleanType(), True),
        StructField("SourceYear", IntegerType(), True),
        StructField("SourceEvent", StringType(), True),
    ]
)

# Define schema for weather data
weather_schema = StructType(
    [
        StructField("Time", StringType(), True),
        StructField("AirTemp", DoubleType(), True),
        StructField("Humidity", DoubleType(), True),
        StructField("Pressure", DoubleType(), True),
        StructField("Rainfall", BooleanType(), True),
        StructField("TrackTemp", DoubleType(), True),
        StructField("WindDirection", IntegerType(), True),
        StructField("WindSpeed", DoubleType(), True),
        StructField("Year", IntegerType(), True),
        StructField("GrandPrix", StringType(), True),
        StructField("SessionType", StringType(), True),
        StructField("DataType", StringType(), True),
        StructField("RecordId", StringType(), True),
        StructField("IsPrediction", BooleanType(), True),
        StructField("SourceYear", IntegerType(), True),
        StructField("SourceEvent", StringType(), True),
    ]
)


# Dictionary to store last known lap times by driver
last_lap_times = {}

# Team mapping dictionary
team_id_mapping = {}


# Function to get team IDs from driver_info collection
def get_team_ids_from_db():
    try:
        client = MongoClient("mongodb://mongodb:27017/")
        db = client["f1db"]

        # Group by TeamName and assign sequential IDs
        pipeline = [{"$group": {"_id": "$TeamName"}}, {"$sort": {"_id": 1}}]

        teams = list(db.driver_info.aggregate(pipeline))

        # Create a mapping with sequential IDs
        team_mapping = {}
        for i, team in enumerate(teams, 1):
            if team["_id"] is not None:
                team_mapping[team["_id"]] = i

        logger.info(f"Found {len(team_mapping)} teams in driver_info collection")
        client.close()
        return team_mapping

    except Exception as e:
        logger.error(f"Error fetching team IDs from MongoDB: {e}")
        return {}


# Create MongoDB indexes before starting streams
def create_mongodb_indexes():
    try:
        # Create MongoDB client
        client = MongoClient("mongodb://mongodb:27017/")
        db = client["f1db"]

        # Create index for car_telemetry collection
        logger.info("Creating index for car_telemetry collection...")
        db.car_telemetry.create_index(
            [("Driver", 1), ("GrandPrix", 1), ("SessionType", 1), ("Time", 1)],
            background=True,
        )

        logger.info("Creating index for car_telemetry collection...")
        db.car_telemetry.create_index(
            [
                ("Driver", 1),
                ("GrandPrix", 1),
                ("SessionType", 1),
                ("LapNumber", 1),
                ("Time", 1),
            ],
            background=True,
        )

        # Create index for car_position collection with LapNumber
        logger.info("Creating index for car_position collection...")
        db.car_position.create_index(
            [
                ("Driver", 1),
                ("GrandPrix", 1),
                ("SessionType", 1),
                ("LapNumber", 1),
                ("Time", 1),
            ],
            background=True,
        )

        # Create index for driver_info collection
        logger.info("Creating index for driver_info collection...")
        db.driver_info.create_index(
            [("Driver", 1), ("Year", 1), ("GrandPrix", 1)], background=True
        )

        # Create index for race_results collection
        logger.info("Creating index for race_results collection...")
        db.race_results.create_index(
            [("Driver", 1), ("Year", 1), ("GrandPrix", 1), ("SessionType", 1)],
            background=True,
        )

        # Create index for weather collection
        logger.info("Creating index for weather collection...")
        db.weather.create_index(
            [("GrandPrix", 1), ("Year", 1), ("SessionType", 1), ("Time", 1)],
            background=True,
        )

        logger.info("MongoDB indexes created successfully")
        client.close()

    except Exception as e:
        logger.error(f"Error creating MongoDB indexes: {e}")


# Create MongoDB indexes before starting streams
create_mongodb_indexes()

# Load initial team IDs
team_id_mapping = get_team_ids_from_db()
logger.info(f"Initially loaded {len(team_id_mapping)} team mappings")


# Function to convert lap time format (MM:SS.mmm) to seconds
def time_to_seconds(time_str):
    if time_str is None or time_str == "" or time_str == "NaT":
        return None

    try:
        # Handle different time formats
        if ":" in time_str:
            parts = time_str.split(":")
            if len(parts) == 3:
                hours = int(parts[0])
                minutes = int(parts[1])
                seconds = float(parts[2])
                return hours * 3600 + minutes * 60 + seconds
            elif len(parts) == 2:
                minutes = int(parts[0])
                seconds = float(parts[1])
                return minutes * 60 + seconds
        else:
            # Just seconds
            return float(time_str)
    except (ValueError, TypeError):
        return None


# Register UDF
time_to_seconds_udf = udf(time_to_seconds, DoubleType())


# Function to process time formats
def process_time_fields(df):
    time_columns = [col_name for col_name in df.columns if "Time" in col_name]

    processed_df = df
    for col_name in time_columns:
        if col_name in processed_df.columns:
            processed_df = processed_df.withColumn(
                col_name,
                when(
                    col(col_name).isNotNull() & col(col_name).contains("days"),
                    regexp_replace(col(col_name), r"^\d+\s+days\s+", ""),
                )
                .when(
                    col(col_name).isNotNull()
                    & ~col(col_name)
                    .cast("string")
                    .rlike(r"^\d{2}:\d{2}:\d{2}(\.\d+)?$|^\d{2}:\d{2}(\.\d+)?$"),
                    # Nullify invalid time formats
                    lit(None),
                )
                .otherwise(col(col_name)),
            )
    return processed_df


# Function to process lap data
def process_lap_data(df):
    processed_df = df.withColumn(
        "DidPit",
        when(
            (col("PitInTime").isNotNull())
            & (~col("PitInTime").isin("", "NaT", "nat", "NAT")),
            lit(True),
        ).otherwise(lit(False)),
    ).withColumn(
        "IsFirstLap", when(col("LapNumber") == 1, lit(True)).otherwise(lit(False))
    )

    # Parse TrackStatus into meaningful flags if TrackStatus is not null
    processed_df = (
        processed_df.withColumn(
            "IsYellowFlag",
            when(
                col("TrackStatus").isNotNull() & col("TrackStatus").contains("2"),
                lit(True),
            ).otherwise(lit(False)),
        )
        .withColumn(
            "IsSafetyCarDeployed",
            when(
                col("TrackStatus").isNotNull() & col("TrackStatus").contains("4"),
                lit(True),
            ).otherwise(lit(False)),
        )
        .withColumn(
            "IsVirtualSafetyCarDeployed",
            when(
                col("TrackStatus").isNotNull() & col("TrackStatus").contains("5"),
                lit(True),
            ).otherwise(lit(False)),
        )
    )

    # Calculate additional metrics (optional)
    processed_df = processed_df.withColumn(
        "AverageSpeed",
        when(
            col("SpeedI1").isNotNull()
            & col("SpeedI2").isNotNull()
            & col("SpeedFL").isNotNull()
            & col("SpeedST").isNotNull(),
            (col("SpeedI1") + col("SpeedI2") + col("SpeedFL") + col("SpeedST")) / 4,
        ).otherwise(None),
    )

    # Make sure year, grand prix and session type are included
    processed_df = (
        processed_df.withColumn(
            "Year", when(col("Year").isNull(), 2023).otherwise(col("Year"))
        )
        .withColumn(
            "GrandPrix",
            when(col("GrandPrix").isNull(), "Unknown").otherwise(col("GrandPrix")),
        )
        .withColumn(
            "SessionType",
            when(col("SessionType").isNull(), "R").otherwise(col("SessionType")),
        )
    )

    return processed_df


# Function to fetch lap timing boundaries for each driver
def get_lap_boundaries_for_session(year, grand_prix, session_type):
    try:
        client = MongoClient("mongodb://mongodb:27017/")
        db = client["f1db"]

        # Get all laps for this session, organized by driver
        lap_boundaries = {}

        pipeline = [
            {
                "$match": {
                    "Year": year,
                    "GrandPrix": grand_prix,
                    "SessionType": session_type,
                }
            },
            {"$sort": {"DriverNumber": 1, "LapNumber": 1}},
        ]

        laps = list(
            db.telemetry.find(
                {"Year": year, "GrandPrix": grand_prix, "SessionType": session_type},
                {
                    "Driver": 1,
                    "DriverNumber": 1,
                    "LapNumber": 1,
                    "LapStartTime": 1,
                    "LapTime": 1,
                    "LapTimeSeconds": 1,
                    "DidPit": 1,
                    "PitInTime": 1,
                },
            ).sort([("Driver", 1), ("LapNumber", 1)])
        )

        for lap in laps:
            driver = lap.get("Driver")
            if not driver:
                continue

            if driver not in lap_boundaries:
                lap_boundaries[driver] = []

            # Calculate lap end time
            lap_start = lap.get("LapStartTime")

            # Determine end time based on whether car pitted or not
            if lap.get("DidPit") and lap.get("PitInTime"):
                lap_end = lap.get("PitInTime")
            elif lap.get("LapTime") and lap.get("LapStartTime"):
                # Calculate end time by adding lap time to start time
                start_parts = lap_start.split(":")
                if len(start_parts) == 3:
                    start_seconds = (
                        int(start_parts[0]) * 3600
                        + int(start_parts[1]) * 60
                        + float(start_parts[2])
                    )
                elif len(start_parts) == 2:
                    start_seconds = int(start_parts[0]) * 60 + float(start_parts[1])
                else:
                    start_seconds = 0

                lap_time_seconds = lap.get("LapTimeSeconds", 0)
                if not lap_time_seconds and lap.get("LapTime"):
                    # Convert lap time to seconds if needed
                    lap_time_seconds = time_to_seconds(lap.get("LapTime"))

                end_seconds = start_seconds + (lap_time_seconds or 0)

                # Format back to time string
                hours = int(end_seconds // 3600)
                minutes = int((end_seconds % 3600) // 60)
                seconds = end_seconds % 60

                lap_end = f"{hours:02d}:{minutes:02d}:{seconds:06.3f}"
            else:
                # If we can't calculate the end time, skip this lap
                continue

            lap_boundaries[driver].append(
                {
                    "LapNumber": lap.get("LapNumber"),
                    "StartTime": lap_start,
                    "EndTime": lap_end,
                }
            )

        client.close()
        return lap_boundaries

    except Exception as e:
        logger.error(f"Error getting lap boundaries: {e}")
        return {}


# Function to determine lap number for a given timestamp
def determine_lap_number(driver, time_str, lap_boundaries):
    if not driver or not time_str or driver not in lap_boundaries:
        return None

    for lap in lap_boundaries[driver]:
        if lap["StartTime"] <= time_str <= lap["EndTime"]:
            return lap["LapNumber"]

    return None


# Get team ID for a team name
def get_team_id(team_name):
    global team_id_mapping

    if not team_name:
        return 0

    # Exact match
    if team_name in team_id_mapping:
        return team_id_mapping[team_name]

    # Case insensitive match
    team_name_lower = team_name.lower()
    for known_team, team_id in team_id_mapping.items():
        if known_team and known_team.lower() == team_name_lower:
            return team_id

    # Assign a new ID
    next_id = max(team_id_mapping.values(), default=0) + 1
    team_id_mapping[team_name] = next_id
    logger.info(f"Assigned new ID {next_id} to team '{team_name}'")
    return next_id


def process_lap_batch(batch_df, batch_id):
    if batch_df.isEmpty():
        logger.info(f"Batch {batch_id} is empty, skipping processing")
        return

    try:
        # Process the batch with standard transformations
        processed_df = process_lap_data(batch_df)

        # Extract valid lap times to update our dictionary
        valid_lap_rows = (
            processed_df.filter(
                (col("LapTime").isNotNull())
                & (col("LapTime") != "")
                & (col("LapTime") != "NaT")
            )
            .select("Driver", "LapTime")
            .collect()
        )

        # Update our global dictionary with any new valid lap times
        for row in valid_lap_rows:
            driver = row["Driver"]
            lap_time = row["LapTime"]
            last_lap_times[driver] = lap_time

        # Now fill any null lap times with the stored last lap time
        # Create a list of rows to write
        rows_to_write = []

        # Convert DataFrame to Python objects for manipulation
        all_rows = processed_df.collect()

        for row in all_rows:
            row_dict = row.asDict()
            driver = row_dict["Driver"]

            # Check if lap time is null and we have a previous time
            if (
                row_dict["LapTime"] is None
                or row_dict["LapTime"] == ""
                or row_dict["LapTime"] == "NaT"
            ) and driver in last_lap_times:
                row_dict["LapTime"] = last_lap_times[driver]
                row_dict["LapTimeFilledByPrevious"] = True
            else:
                row_dict["LapTimeFilledByPrevious"] = False

            # Convert time string to seconds
            if row_dict["LapTime"]:
                row_dict["LapTimeSeconds"] = time_to_seconds(row_dict["LapTime"])
            else:
                row_dict["LapTimeSeconds"] = None

            # Also convert sector times
            if row_dict["Sector1Time"]:
                row_dict["Sector1TimeSeconds"] = time_to_seconds(
                    row_dict["Sector1Time"]
                )
            if row_dict["Sector2Time"]:
                row_dict["Sector2TimeSeconds"] = time_to_seconds(
                    row_dict["Sector2Time"]
                )
            if row_dict["Sector3Time"]:
                row_dict["Sector3TimeSeconds"] = time_to_seconds(
                    row_dict["Sector3Time"]
                )

            # Add TeamID based on Team name
            if "Team" in row_dict and row_dict["Team"]:
                row_dict["TeamID"] = get_team_id(row_dict["Team"])
            else:
                row_dict["TeamID"] = 0

            rows_to_write.append(row_dict)

        # Create a new DataFrame with the filled values and time conversions
        if rows_to_write:
            # Add the new columns to the schema
            new_schema = (
                processed_df.schema.add(
                    StructField("LapTimeFilledByPrevious", BooleanType(), True)
                )
                .add(StructField("LapTimeSeconds", DoubleType(), True))
                .add(StructField("Sector1TimeSeconds", DoubleType(), True))
                .add(StructField("Sector2TimeSeconds", DoubleType(), True))
                .add(StructField("Sector3TimeSeconds", DoubleType(), True))
                .add(StructField("TeamID", IntegerType(), True))
            )

            filled_df = spark.createDataFrame(rows_to_write, new_schema)

            # Write to MongoDB
            write_to_mongodb(filled_df, batch_id, "telemetry")
        else:
            logger.info(f"No rows to write in batch {batch_id}")

    except Exception as e:
        logger.error(f"Error processing batch {batch_id}: {e}")
        # Still try to write the original data without filling
        write_to_mongodb(batch_df, batch_id, "telemetry")


# Function to process driver info data
def process_driver_info(df):
    # No complex processing needed for driver info, but ensure fields are properly formatted
    processed_df = df

    # Make sure year, grand prix and session type are included
    processed_df = (
        processed_df.withColumn(
            "Year", when(col("Year").isNull(), 2023).otherwise(col("Year"))
        )
        .withColumn(
            "GrandPrix",
            when(col("GrandPrix").isNull(), "Unknown").otherwise(col("GrandPrix")),
        )
        .withColumn(
            "SessionType",
            when(col("SessionType").isNull(), "R").otherwise(col("SessionType")),
        )
    )

    return processed_df


# Function to process driver info data with team IDs
def process_driver_info_batch(batch_df, batch_id):
    if batch_df.isEmpty():
        logger.info(f"Batch {batch_id} is empty, skipping processing")
        return

    try:
        # Process driver info with standard transformations
        processed_df = process_driver_info(batch_df)

        # Add TeamID based on TeamName
        rows_to_write = []
        all_rows = processed_df.collect()

        # Process each row and add TeamID
        for row in all_rows:
            row_dict = row.asDict()

            # Add TeamID based on TeamName
            if "TeamName" in row_dict and row_dict["TeamName"]:
                row_dict["TeamID"] = get_team_id(row_dict["TeamName"])
            else:
                row_dict["TeamID"] = 0

            rows_to_write.append(row_dict)

        # Create a new DataFrame with the added team IDs
        if rows_to_write:
            new_schema = processed_df.schema.add(
                StructField("TeamID", IntegerType(), True)
            )
            filled_df = spark.createDataFrame(rows_to_write, new_schema)

            # Write to MongoDB
            write_to_mongodb(filled_df, batch_id, "driver_info")
        else:
            logger.info(f"No driver_info rows to write in batch {batch_id}")

    except Exception as e:
        logger.error(f"Error processing driver_info batch {batch_id}: {e}")
        # Still try to write the original data without the team ID
        write_to_mongodb(batch_df, batch_id, "driver_info")


# Function to process telemetry data
def process_telemetry_data(df):
    # Add derived metrics
    processed_df = (
        df.withColumn(
            "IsBraking", when(col("Brake") > 0, lit(True)).otherwise(lit(False))
        )
        .withColumn(
            "IsAccelerating", when(col("Throttle") > 0, lit(True)).otherwise(lit(False))
        )
        .withColumn("IsDRSOpen", when(col("DRS") > 0, lit(True)).otherwise(lit(False)))
    )

    return processed_df


# Function to process telemetry data batch with team IDs and lap numbers
def process_telemetry_batch(batch_df, batch_id):
    if batch_df.isEmpty():
        logger.info(f"Batch {batch_id} is empty, skipping processing")
        return

    try:
        # Process telemetry with standard transformations
        processed_df = process_telemetry_data(batch_df)

        # Get unique year, grand prix, session combinations to fetch lap boundaries
        session_info = [
            (row["Year"], row["GrandPrix"], row["SessionType"])
            for row in processed_df.select("Year", "GrandPrix", "SessionType")
            .distinct()
            .collect()
        ]

        lap_boundaries_map = {}
        for year, grand_prix, session_type in session_info:
            if None in (year, grand_prix, session_type):
                continue
            lap_boundaries_map[(year, grand_prix, session_type)] = (
                get_lap_boundaries_for_session(year, grand_prix, session_type)
            )

        # Get driver to team mapping from MongoDB
        try:
            client = MongoClient("mongodb://mongodb:27017/")
            db = client["f1db"]

            # Get unique drivers in this batch
            drivers = [
                row["Driver"]
                for row in processed_df.select("Driver").distinct().collect()
            ]

            # Get team info for these drivers
            driver_team_map = {}
            for driver in drivers:
                # Find the most recent driver info record for this driver
                driver_info = (
                    db.driver_info.find({"Driver": driver})
                    .sort([("Year", -1), ("GrandPrix", -1)])
                    .limit(1)
                )
                driver_info = list(driver_info)
                if driver_info:
                    team_name = driver_info[0].get("TeamName")
                    if team_name:
                        driver_team_map[driver] = team_name

            client.close()
        except Exception as e:
            logger.error(f"Error fetching driver-team mapping: {e}")
            driver_team_map = {}

        # Add TeamID and LapNumber to each row
        rows_to_write = []
        all_rows = processed_df.collect()

        # Process each row and add TeamID and LapNumber
        for row in all_rows:
            row_dict = row.asDict()

            # Add TeamID based on Driver
            if "Driver" in row_dict and row_dict["Driver"] in driver_team_map:
                team_name = driver_team_map[row_dict["Driver"]]
                row_dict["Team"] = team_name
                row_dict["TeamID"] = get_team_id(team_name)
            else:
                row_dict["TeamID"] = 0

            # Add LapNumber based on timestamp
            year = row_dict.get("Year")
            grand_prix = row_dict.get("GrandPrix")
            session_type = row_dict.get("SessionType")

            if None not in (year, grand_prix, session_type):
                session_key = (year, grand_prix, session_type)
                if session_key in lap_boundaries_map:
                    lap_boundaries = lap_boundaries_map[session_key]
                    driver = row_dict.get("Driver")
                    time_str = row_dict.get("Time")

                    if driver and time_str and driver in lap_boundaries:
                        lap_number = determine_lap_number(
                            driver, time_str, lap_boundaries
                        )
                        row_dict["LapNumber"] = lap_number

            rows_to_write.append(row_dict)

        # Create a new DataFrame with the added fields
        if rows_to_write:
            new_schema = (
                processed_df.schema.add(StructField("Team", StringType(), True))
                .add(StructField("TeamID", IntegerType(), True))
                .add(StructField("LapNumber", DoubleType(), True))
            )

            filled_df = spark.createDataFrame(rows_to_write, new_schema)

            # Write to MongoDB
            write_to_mongodb(filled_df, batch_id, "car_telemetry")
        else:
            logger.info(f"No car_telemetry rows to write in batch {batch_id}")

    except Exception as e:
        logger.error(f"Error processing car_telemetry batch {batch_id}: {e}")
        # Still try to write the original data without the additions
        write_to_mongodb(batch_df, batch_id, "car_telemetry")


# Function to process position data with team IDs and lap numbers
def process_position_batch(batch_df, batch_id):
    if batch_df.isEmpty():
        logger.info(f"Batch {batch_id} is empty, skipping processing")
        return

    try:
        # Process position data with standard transformations
        processed_df = process_position_data(batch_df)

        # Get unique year, grand prix, session combinations to fetch lap boundaries
        session_info = [
            (row["Year"], row["GrandPrix"], row["SessionType"])
            for row in processed_df.select("Year", "GrandPrix", "SessionType")
            .distinct()
            .collect()
        ]

        lap_boundaries_map = {}
        for year, grand_prix, session_type in session_info:
            if None in (year, grand_prix, session_type):
                continue
            lap_boundaries_map[(year, grand_prix, session_type)] = (
                get_lap_boundaries_for_session(year, grand_prix, session_type)
            )

        # Get driver to team mapping from MongoDB
        try:
            client = MongoClient("mongodb://mongodb:27017/")
            db = client["f1db"]

            # Get unique drivers in this batch
            drivers = [
                row["Driver"]
                for row in processed_df.select("Driver").distinct().collect()
            ]

            # Get team info for these drivers
            driver_team_map = {}
            for driver in drivers:
                # Find the most recent driver info record for this driver
                driver_info = (
                    db.driver_info.find({"Driver": driver})
                    .sort([("Year", -1), ("GrandPrix", -1)])
                    .limit(1)
                )
                driver_info = list(driver_info)
                if driver_info:
                    team_name = driver_info[0].get("TeamName")
                    if team_name:
                        driver_team_map[driver] = team_name

            client.close()
        except Exception as e:
            logger.error(f"Error fetching driver-team mapping: {e}")
            driver_team_map = {}

        # Add TeamID, Team, and LapNumber based on Driver and timestamp
        rows_to_write = []
        all_rows = processed_df.collect()

        # Process each row and add TeamID and LapNumber
        for row in all_rows:
            row_dict = row.asDict()

            # Add TeamID based on Driver
            if "Driver" in row_dict and row_dict["Driver"] in driver_team_map:
                team_name = driver_team_map[row_dict["Driver"]]
                row_dict["Team"] = team_name
                row_dict["TeamID"] = get_team_id(team_name)
            else:
                row_dict["TeamID"] = 0

            # Add LapNumber based on timestamp
            year = row_dict.get("Year")
            grand_prix = row_dict.get("GrandPrix")
            session_type = row_dict.get("SessionType")

            if None not in (year, grand_prix, session_type):
                session_key = (year, grand_prix, session_type)
                if session_key in lap_boundaries_map:
                    lap_boundaries = lap_boundaries_map[session_key]
                    driver = row_dict.get("Driver")
                    time_str = row_dict.get("Time")

                    if driver and time_str and driver in lap_boundaries:
                        lap_number = determine_lap_number(
                            driver, time_str, lap_boundaries
                        )
                        row_dict["LapNumber"] = lap_number

            rows_to_write.append(row_dict)

        # Create a new DataFrame with the added team info and lap number
        if rows_to_write:
            new_schema = (
                processed_df.schema.add(StructField("Team", StringType(), True))
                .add(StructField("TeamID", IntegerType(), True))
                .add(StructField("LapNumber", DoubleType(), True))
            )

            filled_df = spark.createDataFrame(rows_to_write, new_schema)

            # Write to MongoDB
            write_to_mongodb(filled_df, batch_id, "car_position")
        else:
            logger.info(f"No car_position rows to write in batch {batch_id}")

    except Exception as e:
        logger.error(f"Error processing car_position batch {batch_id}: {e}")
        # Still try to write the original data without the team info
        write_to_mongodb(batch_df, batch_id, "car_position")


# Function to process position data - FIXED to use proper sqrt function
def process_position_data(df):
    # Calculate distance from origin using proper sqrt function
    processed_df = df.withColumn(
        "DistanceFromOrigin", sqrt(pow(col("X"), 2) + pow(col("Y"), 2))
    )

    # Fill any missing values
    processed_df = processed_df.na.fill(0, ["X", "Y", "Z"])

    return processed_df


# Function to process race results data
def process_race_results(df):
    # Calculate time gap to leader for race results (where applicable)
    processed_df = df

    # Log the incoming position data for debugging
    logger.info(f"Race results data types: {df.dtypes}")
    logger.info(f"Sample position values: {df.select('Position').limit(5).collect()}")

    # Handle the position values - ensure numeric conversion works properly
    if "Position" in df.columns:
        # First, convert string values to null if they're not numeric
        processed_df = processed_df.withColumn(
            "Position",
            when(
                col("Position").cast("double").isNotNull(),
                col("Position").cast("double"),
            ).otherwise(None),
        )

        # Then create a separate numeric position column
        processed_df = processed_df.withColumn(
            "PositionNumeric",
            when(
                col("Position").isNotNull(), col("Position").cast("integer")
            ).otherwise(None),
        )

        # Add position category (podium, points, etc.)
        processed_df = processed_df.withColumn(
            "PositionCategory",
            when(col("PositionNumeric") <= 3, "Podium")
            .when(col("PositionNumeric") <= 10, "Points")
            .when(col("Points") > 0, "Points")
            .when(col("Status") == "DNF", "DNF")
            .when(col("Status") == "DNS", "DNS")
            .when(col("Status") == "DSQ", "Disqualified")
            .otherwise("No Points"),
        )

    # Make sure year, grand prix and session type are included
    processed_df = (
        processed_df.withColumn(
            "Year", when(col("Year").isNull(), 2023).otherwise(col("Year"))
        )
        .withColumn(
            "GrandPrix",
            when(col("GrandPrix").isNull(), "Unknown").otherwise(col("GrandPrix")),
        )
        .withColumn(
            "SessionType",
            when(col("SessionType").isNull(), "R").otherwise(col("SessionType")),
        )
    )

    return processed_df


# Function to process race results batch with team IDs
def process_results_batch(batch_df, batch_id):
    if batch_df.isEmpty():
        logger.info(f"Batch {batch_id} is empty, skipping processing")
        return

    try:
        # Process race results with standard transformations
        processed_df = process_race_results(batch_df)

        # Add TeamID based on TeamName
        rows_to_write = []
        all_rows = processed_df.collect()

        # Process each row and add TeamID
        for row in all_rows:
            row_dict = row.asDict()

            # Add TeamID based on TeamName
            if "TeamName" in row_dict and row_dict["TeamName"]:
                row_dict["TeamID"] = get_team_id(row_dict["TeamName"])
            else:
                row_dict["TeamID"] = 0

            rows_to_write.append(row_dict)

        # Create a new DataFrame with the added team IDs
        if rows_to_write:
            new_schema = processed_df.schema.add(
                StructField("TeamID", IntegerType(), True)
            )
            filled_df = spark.createDataFrame(rows_to_write, new_schema)

            # Write to MongoDB
            write_to_mongodb(filled_df, batch_id, "race_results")
        else:
            logger.info(f"No race_results rows to write in batch {batch_id}")

    except Exception as e:
        logger.error(f"Error processing race_results batch {batch_id}: {e}")
        # Still try to write the original data without the team ID
        write_to_mongodb(batch_df, batch_id, "race_results")


# Function to process weather data
def process_weather_data(df):
    # Add derived weather metrics
    processed_df = df

    # Calculate temperature difference (track vs air)
    if "TrackTemp" in df.columns and "AirTemp" in df.columns:
        processed_df = processed_df.withColumn(
            "TempDelta",
            when(
                col("TrackTemp").isNotNull() & col("AirTemp").isNotNull(),
                col("TrackTemp") - col("AirTemp"),
            ).otherwise(None),
        )

    # Add weather condition category
    if "Rainfall" in df.columns:
        processed_df = processed_df.withColumn(
            "WeatherCondition", when(col("Rainfall") == True, "Wet").otherwise("Dry")
        )

    # Make sure year, grand prix and session type are included
    processed_df = (
        processed_df.withColumn(
            "Year", when(col("Year").isNull(), 2023).otherwise(col("Year"))
        )
        .withColumn(
            "GrandPrix",
            when(col("GrandPrix").isNull(), "Unknown").otherwise(col("GrandPrix")),
        )
        .withColumn(
            "SessionType",
            when(col("SessionType").isNull(), "R").otherwise(col("SessionType")),
        )
    )

    return processed_df


def write_to_mongodb(batch_df, batch_id, collection):
    if not batch_df.isEmpty():
        count = batch_df.count()
        logger.info(
            f"Writing batch {batch_id} with {count} records to MongoDB collection {collection}"
        )

        try:
            # Cache the dataframe to avoid recomputation
            cached_df = batch_df.cache()

            # Use foreachPartition to write each partition in parallel
            def write_partition(partition_iter):
                import json

                # Create a MongoDB client for this partition
                client = MongoClient("mongodb://mongodb:27017/")
                db = client["f1db"]
                coll = db[collection]

                # Batch records for efficient insertion
                batch_size = 1000
                batch = []

                for row in partition_iter:
                    # Convert Row to dictionary
                    record = row.asDict()
                    batch.append(record)

                    # When batch reaches size, insert and reset
                    if len(batch) >= batch_size:
                        if batch:
                            coll.insert_many(batch, ordered=False)
                            batch = []

                # Insert any remaining records
                if batch:
                    coll.insert_many(batch, ordered=False)

                # Close client connection
                client.close()

            # Apply the function to each partition in parallel
            cached_df.foreachPartition(write_partition)

            # Unpersist the cache after writing
            cached_df.unpersist()

            logger.info(
                f"Successfully wrote batch {batch_id} to MongoDB collection {collection}"
            )
        except Exception as e:
            logger.error(f"Error writing to MongoDB collection {collection}: {e}")


# ----- Process Lap Data -----
logger.info("Starting to read lap data from Kafka")
lap_df = (
    spark.readStream.format("kafka")
    .option("kafka.bootstrap.servers", "kafka:29092")
    .option("subscribe", "telemetry-data")
    .option("startingOffsets", "earliest")
    .option("failOnDataLoss", "false")
    .option("maxOffsetsPerTrigger", 10000)
    .load()
)

# Parse JSON data from Kafka
parsed_lap_df = (
    lap_df.selectExpr("CAST(value AS STRING)")
    .select(from_json(col("value"), lap_schema).alias("data"))
    .select("data.*")
)

# Process time formats
processed_lap_df = process_time_fields(parsed_lap_df)

# Use our new foreachBatch function to process lap data with previous time filling
lap_query = (
    processed_lap_df.writeStream.trigger(processingTime="10 seconds")
    .foreachBatch(process_lap_batch)
    .option("checkpointLocation", "/tmp/checkpoint/lap")
    .start()
)

# ----- Process Telemetry Data -----
logger.info("Starting to read car telemetry data from Kafka")
telemetry_df = (
    spark.readStream.format("kafka")
    .option("kafka.bootstrap.servers", "kafka:29092")
    .option("subscribe", "car-telemetry-data")
    .option("startingOffsets", "earliest")
    .option("failOnDataLoss", "false")
    .option("maxOffsetsPerTrigger", 50000)
    .load()
)

# Parse JSON data from Kafka
parsed_telemetry_df = (
    telemetry_df.selectExpr("CAST(value AS STRING)")
    .select(from_json(col("value"), telemetry_schema).alias("data"))
    .select("data.*")
)

# Process time formats
processed_telemetry_df = process_time_fields(parsed_telemetry_df)

# Process telemetry data with additional features and team IDs
telemetry_query = (
    processed_telemetry_df.writeStream.trigger(processingTime="5 seconds")
    .foreachBatch(process_telemetry_batch)
    .option("checkpointLocation", "/tmp/checkpoint/telemetry")
    .start()
)

# ----- Process Position Data -----
logger.info("Starting to read car position data from Kafka")
position_df = (
    spark.readStream.format("kafka")
    .option("kafka.bootstrap.servers", "kafka:29092")
    .option("subscribe", "car-position-data")
    .option("startingOffsets", "earliest")
    .option("failOnDataLoss", "false")
    .option("maxOffsetsPerTrigger", 50000)
    .load()
)

# Parse JSON data from Kafka
parsed_position_df = (
    position_df.selectExpr("CAST(value AS STRING)")
    .select(from_json(col("value"), position_schema).alias("data"))
    .select("data.*")
)

# Process time formats
processed_position_df = process_time_fields(parsed_position_df)

# Process position data with team IDs
position_query = (
    processed_position_df.writeStream.trigger(processingTime="5 seconds")
    .foreachBatch(process_position_batch)
    .option("checkpointLocation", "/tmp/checkpoint/position")
    .start()
)

# ----- Process Driver Info Data -----
logger.info("Starting to read driver info data from Kafka")
driver_info_df = (
    spark.readStream.format("kafka")
    .option("kafka.bootstrap.servers", "kafka:29092")
    .option("subscribe", "driver-info-data")
    .option("startingOffsets", "earliest")
    .option("failOnDataLoss", "false")
    .option("maxOffsetsPerTrigger", 10000)
    .load()
)

# Parse JSON data from Kafka
parsed_driver_info_df = (
    driver_info_df.selectExpr("CAST(value AS STRING)")
    .select(from_json(col("value"), driver_info_schema).alias("data"))
    .select("data.*")
)

# Process driver info data with team IDs
driver_info_query = (
    parsed_driver_info_df.writeStream.trigger(processingTime="10 seconds")
    .foreachBatch(process_driver_info_batch)
    .option("checkpointLocation", "/tmp/checkpoint/driver_info")
    .start()
)

# ----- Process Race Results Data -----
logger.info("Starting to read race results data from Kafka")
results_df = (
    spark.readStream.format("kafka")
    .option("kafka.bootstrap.servers", "kafka:29092")
    .option("subscribe", "race-results-data")
    .option("startingOffsets", "earliest")
    .option("failOnDataLoss", "false")
    .option("maxOffsetsPerTrigger", 10000)
    .load()
)

# Parse JSON data from Kafka
parsed_results_df = (
    results_df.selectExpr("CAST(value AS STRING)")
    .select(from_json(col("value"), results_schema).alias("data"))
    .select("data.*")
)

# Process time formats
processed_results_df = process_time_fields(parsed_results_df)

# Process race results data with team IDs
results_query = (
    processed_results_df.writeStream.trigger(processingTime="10 seconds")
    .foreachBatch(process_results_batch)
    .option("checkpointLocation", "/tmp/checkpoint/race_results")
    .start()
)

# ----- Process Weather Data -----
logger.info("Starting to read weather data from Kafka")
weather_df = (
    spark.readStream.format("kafka")
    .option("kafka.bootstrap.servers", "kafka:29092")
    .option("subscribe", "weather-data")
    .option("startingOffsets", "earliest")
    .option("failOnDataLoss", "false")
    .option("maxOffsetsPerTrigger", 10000)
    .load()
)

# Parse JSON data from Kafka
parsed_weather_df = (
    weather_df.selectExpr("CAST(value AS STRING)")
    .select(from_json(col("value"), weather_schema).alias("data"))
    .select("data.*")
)

# Process time formats
processed_weather_df = process_time_fields(parsed_weather_df)

# Process weather data
final_weather_df = process_weather_data(processed_weather_df)

# Write weather data to MongoDB
weather_query = (
    final_weather_df.writeStream.trigger(processingTime="10 seconds")
    .foreachBatch(
        lambda batch_df, batch_id: write_to_mongodb(batch_df, batch_id, "weather")
    )
    .option("checkpointLocation", "/tmp/checkpoint/weather")
    .start()
)

logger.info("All streaming queries started with optimized settings")

# Wait for all queries to terminate
spark.streams.awaitAnyTermination()
