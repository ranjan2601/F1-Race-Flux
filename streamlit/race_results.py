import os
import streamlit as st
import pandas as pd
import pymongo
import plotly.express as px
import plotly.graph_objects as go
from typing import Dict, Any, Optional

# MongoDB connection settings
MONGO_URI = os.environ.get("MONGO_URI", "mongodb://mongodb:27017/")
DB_NAME = os.environ.get("DB_NAME", "f1db")


# Custom styling for race results
def load_results_styles():
    st.markdown(
        """
    <style>
        .results-card {
            background-color: #1a1a1a;
            border-radius: 5px;
            padding: 1rem;
            margin-bottom: 1rem;
            border: 1px solid #333;
        }
        .results-title {
            font-size: 1.5rem;
            font-weight: bold;
            margin-bottom: 1rem;
            color: white;
            text-align: center;
        }
        .team-indicator {
            display: inline-block;
            width: 4px;
            height: 16px;
            margin-right: 8px;
            border-radius: 2px;
        }
        .driver-name {
            font-weight: bold;
        }
        .position-cell {
            font-weight: bold;
            font-size: 1.1rem;
        }
        /* Table styling */
        .dataframe {
            width: 100%;
            color: white;
            border-collapse: collapse;
        }
        .dataframe th {
            background-color: #2a2a2a;
            padding: 8px;
            border-bottom: 2px solid #444;
            text-align: left;
        }
        .dataframe td {
            padding: 8px;
            border-bottom: 1px solid #333;
        }
        .dataframe tr:hover {
            background-color: #2a2a2a;
        }
    </style>
    """,
        unsafe_allow_html=True,
    )


# MongoDB connection function
@st.cache_resource
def get_mongodb_client():
    return pymongo.MongoClient(MONGO_URI)


# Function to check if race results are available
def check_race_results_available(year: int, event: str) -> bool:
    try:
        client = get_mongodb_client()
        db = client[DB_NAME]
        results_collection = db["race_results"]

        # Query MongoDB for race results
        query = {"Year": year, "GrandPrix": event, "SessionType": "Race"}

        # Check if any results exist
        count = results_collection.count_documents(query)
        if count > 0:
            return True

        # If no results in race_results collection, check telemetry collection
        telemetry_collection = db["telemetry"]
        telemetry_query = {
            "Year": year,
            "GrandPrix": event,
            "SessionType": "Race",
            "LapNumber": {"$exists": True},
        }

        telemetry_count = telemetry_collection.count_documents(telemetry_query)
        return telemetry_count > 0

    except Exception as e:
        st.error(f"Error checking race results availability: {e}")
        return False


# Function to fetch race results for a specific session
def fetch_race_results(year: int, event: str) -> pd.DataFrame:
    try:
        client = get_mongodb_client()
        db = client[DB_NAME]
        results_collection = db["race_results"]

        # Query MongoDB for race results
        query = {"Year": year, "GrandPrix": event, "SessionType": "Race"}

        # Fetch the data and convert to a list of dictionaries
        cursor = results_collection.find(query)
        data = list(cursor)

        # Convert to DataFrame
        if data:
            df = pd.DataFrame(data)
            # Remove _id column
            if "_id" in df.columns:
                df = df.drop("_id", axis=1)

            # Clean and format the data
            df = process_race_results(df)
            return df
        else:
            # If no data in race_results, try to look in the telemetry collection for position data
            telemetry_collection = db["telemetry"]
            telemetry_query = {
                "Year": year,
                "GrandPrix": event,
                "SessionType": "Race",
                "LapNumber": {"$exists": True},
            }

            telemetry_cursor = telemetry_collection.find(telemetry_query)
            telemetry_data = list(telemetry_cursor)

            if telemetry_data:
                # Process telemetry data to get race results
                return process_telemetry_for_results(telemetry_data)

            # If still no data, return empty DataFrame
            return pd.DataFrame()
    except Exception as e:
        st.error(f"Error fetching race results: {e}")
        return pd.DataFrame()


# Function to process telemetry data to get race results
def process_telemetry_for_results(telemetry_data: list) -> pd.DataFrame:
    try:
        # Get the final lap for each driver
        driver_laps = {}

        for lap in telemetry_data:
            driver = lap.get("Driver")
            lap_num = lap.get("LapNumber")

            if driver and lap_num:
                # Only keep the highest lap number for each driver
                if driver not in driver_laps or lap_num > driver_laps[driver].get(
                    "LapNumber", 0
                ):
                    driver_laps[driver] = lap

        # Convert to a list of final positions
        final_results = []
        for driver, lap in driver_laps.items():
            result = {
                "Driver": driver,
                "DriverNumber": lap.get("DriverNumber"),
                "Position": lap.get("Position"),
                "Team": lap.get("Team"),
                "TeamName": lap.get("Team"),
                "TeamID": lap.get("TeamID"),
                "Year": lap.get("Year"),
                "GrandPrix": lap.get("GrandPrix"),
                "SessionType": lap.get("SessionType"),
                "Status": "Finished",
            }
            final_results.append(result)

        # Convert to DataFrame and sort by position
        df = pd.DataFrame(final_results)
        df = df.sort_values(by="Position")

        return process_race_results(df)
    except Exception as e:
        st.error(f"Error processing telemetry for results: {e}")
        return pd.DataFrame()


# Function to process and format race results data
def process_race_results(df: pd.DataFrame) -> pd.DataFrame:
    # Make sure we have essential columns
    for col in ["Driver", "Position", "Team", "TeamName", "Status", "Points"]:
        if col not in df.columns:
            df[col] = None

    # Convert position to numeric value for sorting
    if "Position" in df.columns:
        df["PositionNumeric"] = pd.to_numeric(df["Position"], errors="coerce")
        df["PositionNumeric"] = df["PositionNumeric"].fillna(999)
    else:
        df["PositionNumeric"] = 999

    # Sort by position
    df = df.sort_values(by="PositionNumeric")

    # Add a position display column
    df["DisplayPosition"] = df["PositionNumeric"].apply(
        lambda x: int(x) if x != 999 else "DNF"
    )

    # Use Team column if TeamName is not available
    if "TeamName" not in df.columns or df["TeamName"].isna().all():
        if "Team" in df.columns:
            df["TeamName"] = df["Team"]

    # Format driver info
    if "Driver" in df.columns and "DriverNumber" in df.columns:
        df["DriverDisplay"] = df.apply(
            lambda row: (
                f"{row['Driver']} ({row['DriverNumber']})"
                if pd.notna(row["DriverNumber"])
                else row["Driver"]
            ),
            axis=1,
        )
    else:
        df["DriverDisplay"] = df["Driver"]

    # Add position category
    df["PositionCategory"] = df.apply(
        lambda row: (
            "Podium"
            if row["PositionNumeric"] <= 3
            else (
                "Points"
                if row["PositionNumeric"] <= 10
                else "DNF" if row["Status"] == "DNF" else "No Points"
            )
        ),
        axis=1,
    )

    return df


# Function to create team colors mapping
def create_team_colors() -> Dict[str, str]:
    return {
        "Red Bull Racing": "#3671C6",
        "Ferrari": "#F91536",
        "Aston Martin": "#5E8FAA",
        "McLaren": "#F58020",
        "Mercedes": "#6CD3BF",
        "RB": "#C8C8C8",
        "Haas F1 Team": "#B6BABD",
        "Williams": "#37BEDD",
        "Alpine": "#2293D1",
        "Kick Sauber": "#00CF46",
        # Default for any unknown team
        "Unknown": "#FFFFFF",
    }


# Function to display race results table
def display_race_results_table(df: pd.DataFrame, team_colors: Dict[str, str]):
    if df.empty:
        st.warning("No race results data available")
        return

    # Create a custom dataframe for display
    display_df = df.copy()

    # Select columns to display and rename them
    columns_to_display = [
        "DisplayPosition",
        "DriverDisplay",
        "TeamName",
        "Status",
        "Points",
    ]

    # Ensure all required columns exist
    for col in columns_to_display:
        if col not in display_df.columns:
            display_df[col] = None

    # Select only the columns we want to display
    display_df = display_df[columns_to_display]

    # Rename columns for better display
    display_df.columns = ["Pos", "Driver", "Team", "Status", "Pts"]

    # Convert to HTML with styling
    html = '<table class="dataframe">'

    # Add header
    html += "<thead><tr>"
    for col in display_df.columns:
        html += f"<th>{col}</th>"
    html += "</tr></thead>"

    # Add rows
    html += "<tbody>"
    for _, row in display_df.iterrows():
        html += "<tr>"

        # Position column
        html += f'<td class="position-cell">{row["Pos"]}</td>'

        # Driver column with team color indicator
        team = row["Team"]
        color = team_colors.get(team, team_colors["Unknown"])
        html += f'<td><div class="team-indicator" style="background-color: {color};"></div><span class="driver-name">{row["Driver"]}</span></td>'

        # Remaining columns
        html += f'<td>{row["Team"]}</td>'
        html += f'<td>{row["Status"] if pd.notna(row["Status"]) else "-"}</td>'
        html += f'<td>{row["Pts"] if pd.notna(row["Pts"]) else "-"}</td>'

        html += "</tr>"
    html += "</tbody></table>"

    # Display the HTML table
    st.markdown(html, unsafe_allow_html=True)


# Function to display race results as a simple grid
def display_results_grid(df: pd.DataFrame, team_colors: Dict[str, str]):
    if df.empty:
        st.warning("No race results data available")
        return

    st.write("### Race Classification")

    # Create a grid view
    cols = st.columns(5)

    for i, (_, row) in enumerate(df.iterrows()):
        pos = i + 1 if row["PositionNumeric"] != 999 else "DNF"
        driver = row["Driver"]
        team = (
            row["TeamName"]
            if "TeamName" in row and pd.notna(row["TeamName"])
            else row.get("Team", "Unknown")
        )
        color = team_colors.get(team, team_colors["Unknown"])

        with cols[i % 5]:
            st.markdown(
                f"""
                <div style="padding: 10px; margin-bottom: 10px; border-left: 4px solid {color}; background-color: #222;">
                    <div style="font-size: 1.2rem; font-weight: bold;">{pos}. {driver}</div>
                    <div style="font-size: 0.9rem; color: #aaa;">{team}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )


# Main function to display race results
def show_race_results(year: int, event: str):
    # Initialize session state variables if not already set
    if "race_results_loaded" not in st.session_state:
        st.session_state.race_results_loaded = False
        st.session_state.race_results_data = None
        st.session_state.last_year_event = None

    # Check if year/event has changed
    current_selection = (year, event)
    selection_changed = current_selection != st.session_state.last_year_event

    # Update the last selection
    st.session_state.last_year_event = current_selection

    # Load custom styles
    load_results_styles()

    st.markdown("---")
    st.subheader("Race Results")

    # First, check if results are available for this session
    results_available = check_race_results_available(year, event)

    # If results are available and haven't been loaded or selection changed, load them automatically
    if results_available and (
        not st.session_state.race_results_loaded or selection_changed
    ):
        with st.spinner(f"Loading race results for {event} {year}..."):
            # Fetch the race results
            race_results = fetch_race_results(year, event)

            if not race_results.empty:
                st.session_state.race_results_data = race_results
                st.session_state.race_results_loaded = True
            else:
                st.error(f"No race results found for {event} {year}")
                st.session_state.race_results_loaded = False
                st.session_state.race_results_data = None

    # If results are not available, show a message
    elif not results_available:
        st.info(f"No race results available for {event} {year}")
        st.session_state.race_results_loaded = False
        st.session_state.race_results_data = None

        # Provide an option to load telemetry data as a fallback
        if st.button("Try to generate results from telemetry data"):
            with st.spinner("Generating race results from telemetry..."):
                race_results = fetch_race_results(year, event)
                if not race_results.empty:
                    st.session_state.race_results_data = race_results
                    st.session_state.race_results_loaded = True
                else:
                    st.error("Unable to generate results from telemetry data")

    # If we have race results data, show the visualization
    if (
        st.session_state.race_results_loaded
        and st.session_state.race_results_data is not None
    ):
        # Create team colors mapping
        team_colors = create_team_colors()

        # Race results section
        st.markdown('<div class="results-card">', unsafe_allow_html=True)
        st.markdown(
            '<div class="results-title">Final Classification</div>',
            unsafe_allow_html=True,
        )

        # Display the results table
        display_race_results_table(st.session_state.race_results_data, team_colors)

        # Display results grid as alternative view
        if st.checkbox("Show Grid View"):
            display_results_grid(st.session_state.race_results_data, team_colors)

        st.markdown("</div>", unsafe_allow_html=True)

        # Raw data view
        with st.expander("View Raw Race Results Data"):
            st.dataframe(st.session_state.race_results_data, use_container_width=True)
