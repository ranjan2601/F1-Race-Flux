import os
import streamlit as st
import pandas as pd
import numpy as np
import pymongo
import plotly.express as px
import plotly.graph_objects as go
from typing import Dict, Any, List, Tuple
from functools import lru_cache

# MongoDB connection settings
MONGO_URI = os.environ.get("MONGO_URI", "mongodb://mongodb:27017/")
DB_NAME = os.environ.get("DB_NAME", "f1db")


# MongoDB connection function
@st.cache_resource
def get_mongodb_client():
    return pymongo.MongoClient(MONGO_URI)


# Function to get available sessions
def get_available_sessions():
    try:
        client = get_mongodb_client()
        db = client[DB_NAME]

        # Query distinct values from telemetry collection
        telemetry_collection = db["telemetry"]

        # Get distinct years
        years = sorted(telemetry_collection.distinct("Year"), reverse=True)

        # Create a nested dictionary to store available sessions
        available_sessions = {}

        for year in years:
            # Get distinct events for this year
            events = sorted(telemetry_collection.distinct("GrandPrix", {"Year": year}))
            available_sessions[year] = {}

            for event in events:
                # Get distinct session types for this event
                session_types = sorted(
                    telemetry_collection.distinct(
                        "SessionType", {"Year": year, "GrandPrix": event}
                    )
                )
                available_sessions[year][event] = session_types

        return available_sessions

    except Exception as e:
        st.error(f"Error fetching available sessions: {e}")
        return {}


# Function to get available drivers for a session
def get_available_drivers(year: int, event: str, session_type: str) -> List[Dict]:
    try:
        client = get_mongodb_client()
        db = client[DB_NAME]

        # Get driver info for this session
        telemetry_collection = db["telemetry"]
        query = {"Year": year, "GrandPrix": event, "SessionType": session_type}

        # Get distinct drivers
        driver_data = list(
            telemetry_collection.find(
                query,
                {"Driver": 1, "DriverNumber": 1, "Team": 1, "TeamID": 1, "_id": 0},
            ).distinct("Driver")
        )

        # Get complete driver info for each driver
        drivers = []
        for driver_code in driver_data:
            # Find the first document for this driver to get team info
            driver_doc = telemetry_collection.find_one(
                {
                    "Year": year,
                    "GrandPrix": event,
                    "SessionType": session_type,
                    "Driver": driver_code,
                },
                {"Driver": 1, "DriverNumber": 1, "Team": 1, "TeamID": 1, "_id": 0},
            )

            if driver_doc:
                drivers.append(
                    {
                        "Driver": driver_doc.get("Driver", ""),
                        "DriverNumber": driver_doc.get("DriverNumber", ""),
                        "Team": driver_doc.get("Team", "Unknown Team"),
                        "TeamID": driver_doc.get("TeamID", 0),
                        "DisplayName": f"{driver_doc.get('Driver', '')} ({driver_doc.get('Team', 'Unknown')})",
                    }
                )

        return sorted(drivers, key=lambda x: x["Driver"])

    except Exception as e:
        st.error(f"Error fetching available drivers: {e}")
        return []


# Function to get available laps for a driver
def get_driver_laps(
    year: int, event: str, session_type: str, driver: str
) -> List[Dict]:
    try:
        client = get_mongodb_client()
        db = client[DB_NAME]

        telemetry_collection = db["telemetry"]
        query = {
            "Year": year,
            "GrandPrix": event,
            "SessionType": session_type,
            "Driver": driver,
            "Deleted": {"$ne": True},
            "LapTimeSeconds": {"$ne": None},
        }

        # Get lap data
        lap_data = list(
            telemetry_collection.find(
                query,
                {"LapNumber": 1, "LapTimeSeconds": 1, "IsPersonalBest": 1, "_id": 0},
            ).sort("LapNumber", 1)
        )

        # Format lap display names
        for lap in lap_data:
            lap_time = lap.get("LapTimeSeconds", 0)
            minutes = int(lap_time // 60)
            seconds = lap_time % 60
            lap["DisplayName"] = f"Lap {lap['LapNumber']} - {minutes}:{seconds:.3f}"
            if lap.get("IsPersonalBest", False):
                lap["DisplayName"] += " (Personal Best)"

        return lap_data

    except Exception as e:
        st.error(f"Error fetching driver laps: {e}")
        return []


# Function to get a driver's fastest lap
def get_driver_fastest_lap(
    year: int, event: str, session_type: str, driver: str
) -> int:
    try:
        client = get_mongodb_client()
        db = client[DB_NAME]

        telemetry_collection = db["telemetry"]
        query = {
            "Year": year,
            "GrandPrix": event,
            "SessionType": session_type,
            "Driver": driver,
            "Deleted": {"$ne": True},
            "LapTimeSeconds": {"$ne": None},
        }

        # Sort by lap time and get the fastest
        fastest_lap = telemetry_collection.find_one(
            query, {"LapNumber": 1, "_id": 0}, sort=[("LapTimeSeconds", 1)]
        )

        if fastest_lap:
            return fastest_lap.get("LapNumber")
        return 1  # Default to lap 1 if no fastest lap found

    except Exception as e:
        st.error(f"Error fetching fastest lap: {e}")
        return 1


# Function to get telemetry data for a specific lap
def get_lap_telemetry(
    year: int, event: str, session_type: str, driver: str, lap_number: int
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    try:
        client = get_mongodb_client()
        db = client[DB_NAME]

        # Get driver number from telemetry collection
        telemetry_collection = db["telemetry"]
        driver_info = telemetry_collection.find_one(
            {
                "Year": year,
                "GrandPrix": event,
                "SessionType": session_type,
                "Driver": driver,
            },
            {"DriverNumber": 1},
        )

        if not driver_info:
            return pd.DataFrame(), pd.DataFrame()

        driver_number = driver_info.get("DriverNumber")

        # Get car position data for this lap
        position_collection = db["car_position"]
        position_query = {
            "Year": year,
            "GrandPrix": event,
            "SessionType": session_type,
            "Driver": driver_number,
            "LapNumber": lap_number,
        }

        position_data = list(position_collection.find(position_query))

        # Get car telemetry data for this lap
        telemetry_collection = db["car_telemetry"]
        telemetry_query = {
            "Year": year,
            "GrandPrix": event,
            "SessionType": session_type,
            "Driver": driver_number,
            "LapNumber": lap_number,
        }

        telemetry_data = list(telemetry_collection.find(telemetry_query))

        # Convert to DataFrames
        position_df = pd.DataFrame(position_data)
        telemetry_df = pd.DataFrame(telemetry_data)

        # Remove _id columns if present
        if "_id" in position_df.columns:
            position_df = position_df.drop("_id", axis=1)
        if "_id" in telemetry_df.columns:
            telemetry_df = telemetry_df.drop("_id", axis=1)

        return position_df, telemetry_df

    except Exception as e:
        st.error(f"Error fetching lap telemetry: {e}")
        return pd.DataFrame(), pd.DataFrame()


# Function to merge position and telemetry data
def merge_telemetry_with_position(
    position_df: pd.DataFrame, telemetry_df: pd.DataFrame
) -> pd.DataFrame:
    if position_df.empty or telemetry_df.empty:
        return pd.DataFrame()

    try:
        # Extract just the X and Y coordinates from position data
        merged_df = (
            position_df[["X", "Y"]].copy()
            if "X" in position_df.columns and "Y" in position_df.columns
            else pd.DataFrame()
        )

        if merged_df.empty:
            return pd.DataFrame()

        # Initialize Speed column with zeros
        merged_df["Speed"] = 0

        # If we have speed data in telemetry, use it
        if "Speed" in telemetry_df.columns and len(telemetry_df) > 0:
            # Reindex or sample to match lengths
            speed_values = telemetry_df["Speed"].values

            # Simple approach - just use available speed values and pad with zeros if needed
            n_positions = len(merged_df)
            n_speeds = len(speed_values)

            # Use the minimum of the two lengths
            min_length = min(n_positions, n_speeds)

            # Assign the speed values we have
            merged_df.loc[: min_length - 1, "Speed"] = speed_values[:min_length]

            # Fill any missing values with the previous valid value
            merged_df["Speed"] = merged_df["Speed"].replace(0, None).ffill().fillna(0)

        return merged_df

    except Exception as e:
        st.error(f"Error merging telemetry data: {e}")
        return pd.DataFrame()


# Function to create the track heatmap
def create_speed_heatmap(
    merged_df: pd.DataFrame, driver_name: str, lap_number: int
) -> go.Figure:
    if merged_df.empty:
        # Create empty figure with message
        fig = go.Figure()
        fig.update_layout(
            title=f"No data available for {driver_name}, Lap {lap_number}",
            template="plotly_dark",
        )
        return fig

    # Create figure
    fig = go.Figure()

    fig.add_trace(
        go.Scatter(
            x=merged_df["X"],
            y=merged_df["Y"],
            mode="markers",
            marker=dict(
                size=8,
                color=merged_df["Speed"],
                colorscale="Viridis",
                colorbar=dict(
                    title="Speed (km/h)",
                    tickmode="array",
                    tickvals=[50, 100, 150, 200, 250, 300],
                    ticks="outside",
                ),
                line=dict(width=0),
            ),
            hovertemplate="Speed: %{marker.color:.0f} km/h<extra></extra>",
        )
    )

    # Connect the dots with a simple line to show the track path
    fig.add_trace(
        go.Scatter(
            x=merged_df["X"],
            y=merged_df["Y"],
            mode="lines",
            line=dict(width=1, color="rgba(255, 255, 255, 0.3)"),
            hoverinfo="none",
            showlegend=False,
        )
    )

    # Calculate track boundaries for good display
    x_range = [
        merged_df["X"].min() - abs(merged_df["X"].min() * 0.1),
        merged_df["X"].max() + abs(merged_df["X"].max() * 0.1),
    ]
    y_range = [
        merged_df["Y"].min() - abs(merged_df["Y"].min() * 0.1),
        merged_df["Y"].max() + abs(merged_df["Y"].max() * 0.1),
    ]

    if len(merged_df) > 0:
        start_x = merged_df["X"].iloc[0]
        start_y = merged_df["Y"].iloc[0]
        fig.add_annotation(
            x=start_x,
            y=start_y,
            text="🏁",
            showarrow=False,
            font=dict(size=24),
            xanchor="center",
            yanchor="middle",
        )

    # Set layout properties
    fig.update_layout(
        title=f"{driver_name} - Lap {lap_number} - Speed Heatmap",
        template="plotly_dark",
        showlegend=False,
        xaxis=dict(range=x_range, showgrid=False, zeroline=False, showticklabels=False),
        yaxis=dict(
            range=y_range,
            showgrid=False,
            zeroline=False,
            showticklabels=False,
            scaleanchor="x",
            scaleratio=1,
        ),
        margin=dict(l=20, r=20, t=50, b=20),
        height=700,
    )

    return fig


# Main function to display the track speed heatmap
def show_track_speed_heatmap(year: int, event: str, session_type: str):
    st.markdown("---")
    st.subheader("Track Speed Heatmap")

    # Get available drivers
    drivers = get_available_drivers(year, event, session_type)

    if not drivers:
        st.warning(f"No driver data available for {event} {year} {session_type}")
        return

    # Create layout with columns
    col1, col2, col3 = st.columns([1, 1, 1])

    # Driver selection
    with col1:
        driver_options = {d["DisplayName"]: d for d in drivers}
        selected_driver_key = st.selectbox(
            "Select Driver",
            options=list(driver_options.keys()),
            key="speed_heatmap_driver",
        )

        if selected_driver_key:
            selected_driver = driver_options[selected_driver_key]

    # Get laps for the selected driver
    if "selected_driver" in locals():
        laps = get_driver_laps(year, event, session_type, selected_driver["Driver"])
        fastest_lap = get_driver_fastest_lap(
            year, event, session_type, selected_driver["Driver"]
        )

        # Lap selection
        with col2:
            # Create lap selection options
            lap_options = {lap["DisplayName"]: lap["LapNumber"] for lap in laps}

            if lap_options:
                selected_lap_key = st.selectbox(
                    "Select Lap",
                    options=list(lap_options.keys()),
                    key="speed_heatmap_lap",
                )

                if selected_lap_key:
                    selected_lap = lap_options[selected_lap_key]
            else:
                st.warning("No valid laps available for this driver")
                return

        # Option to display fastest lap
        with col3:
            show_fastest = st.checkbox(
                "Show Fastest Lap", value=False, key="speed_heatmap_fastest"
            )

            if show_fastest:
                st.info(f"Fastest Lap: {fastest_lap}")
                selected_lap = fastest_lap

        # Get telemetry for the selected lap
        position_df, telemetry_df = get_lap_telemetry(
            year, event, session_type, selected_driver["Driver"], selected_lap
        )

        # Merge position and telemetry data
        merged_df = merge_telemetry_with_position(position_df, telemetry_df)

        # Create and display the heatmap
        if not merged_df.empty:
            fig = create_speed_heatmap(
                merged_df, selected_driver["Driver"], selected_lap
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.error(
                f"No data available for {selected_driver['Driver']}, Lap {selected_lap}"
            )


# If run directly, test with a hard-coded example
if __name__ == "__main__":
    st.set_page_config(
        page_title="F1 Track Speed Heatmap", page_icon="🏎️", layout="wide"
    )

    st.title("F1 Track Speed Heatmap")
    show_track_speed_heatmap(2024, "Saudi Arabian Grand Prix", "Race")
