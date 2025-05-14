import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import pymongo
from typing import Dict, List, Tuple
import os

# MongoDB connection settings
MONGO_URI = os.environ.get("MONGO_URI", "mongodb://mongodb:27017/")
DB_NAME = os.environ.get("DB_NAME", "f1db")

# Custom color palette for consistent driver colors
TEAM_COLORS = {
    "Red Bull": "#3671C6",
    "Mercedes": "#6CD3BF",
    "Ferrari": "#F91536",
    "McLaren": "#F58020",
    "Aston Martin": "#5E8FAA",
    "Alpine": "#2293D1",
    "Williams": "#37BEDD",
    "AlphaTauri": "#C8C8C8",
    "RB": "#C8C8C8",
    "Racing Bulls": "#C8C8C8",
    "Alfa Romeo": "#00CF46",
    "Sauber": "#00CF46",
    "Kick Sauber": "#00CF46",
    "Haas": "#B6BABD",
}


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


# Function to get lap times for a driver
def get_driver_lap_times(year: int, event: str, session_type: str, driver: str):
    try:
        client = get_mongodb_client()
        db = client[DB_NAME]

        telemetry_collection = db["telemetry"]
        query = {
            "Year": year,
            "GrandPrix": event,
            "SessionType": session_type,
            "Driver": driver,
        }

        # Get lap data
        lap_data = list(
            telemetry_collection.find(
                query,
                {
                    "LapNumber": 1,
                    "LapTimeSeconds": 1,
                    "Sector1TimeSeconds": 1,
                    "Sector2TimeSeconds": 1,
                    "Sector3TimeSeconds": 1,
                    "IsPersonalBest": 1,
                    "Deleted": 1,
                    "Team": 1,
                    "TeamID": 1,
                    "_id": 0,
                },
            ).sort("LapNumber", 1)
        )

        # Convert to DataFrame
        df = pd.DataFrame(lap_data)

        # Filter out invalid laps (deleted, missing lap times, etc.)
        if not df.empty:
            df = df[~df["Deleted"]] if "Deleted" in df.columns else df
            df = (
                df[~df["LapTimeSeconds"].isna()]
                if "LapTimeSeconds" in df.columns
                else df
            )

        return df

    except Exception as e:
        st.error(f"Error fetching lap times: {e}")
        return pd.DataFrame()


# Improved function to get team color
def get_team_color(team_id: int = None, team_name: str = None) -> str:
    """
    Get team color based on team name or team ID.
    Prioritizes team name if provided.
    """
    # Default color if nothing matches
    default_color = "#FFFFFF"

    # Try to determine color from team name first
    if team_name:
        team_name = team_name.lower()

        # Red Bull and RB
        if "red bull" in team_name:
            return "#3671C6"  # Blue
        elif (
            team_name == "rb"
            or "racing bulls" in team_name
            or "alpha tauri" in team_name
        ):
            return "#C8C8C8"  # Greyish white

        # Ferrari
        elif "ferrari" in team_name:
            return "#F91536"  # Red

        # Mercedes
        elif "mercedes" in team_name:
            return "#6CD3BF"  # Turquoise

        # McLaren
        elif "mclaren" in team_name:
            return "#F58020"  # Orange

        # Alpine
        elif "alpine" in team_name:
            return "#2293D1"  # Blue

        # Aston Martin
        elif "aston" in team_name:
            return "#5E8FAA"  # British racing green

        # Williams
        elif "williams" in team_name:
            return "#37BEDD"  # Light blue

        # Haas
        elif "haas" in team_name:
            return "#B6BABD"  # White/silver

        # Sauber (includes Alfa Romeo and Kick Sauber)
        elif "sauber" in team_name or "alfa" in team_name:
            return "#00CF46"  # Green

    # If we couldn't determine from name, fall back to team_id
    if team_id is not None:
        team_colors = {
            1: "#3671C6",  # Red Bull
            2: "#37BEDD",  # Williams
            3: "#F91536",  # Ferrari
            4: "#6CD3BF",  # Mercedes
            5: "#2293D1",  # Alpine
            6: "#F58020",  # McLaren
            7: "#5E8FAA",  # Aston Martin
            8: "#B6BABD",  # Haas
            9: "#00CF46",  # Sauber
            10: "#C8C8C8",  # RB
            0: "#FFFFFF",  # Default
        }
        return team_colors.get(team_id, default_color)

    # If all else fails, return default
    return default_color


# Convert seconds to minutes:seconds format for display
def format_lap_time(seconds):
    if pd.isna(seconds):
        return ""

    minutes = int(seconds // 60)
    remaining_seconds = seconds % 60
    return f"{minutes}:{remaining_seconds:.3f}"


# Function to generate lap time comparison visualization and tables
def generate_lap_comparison(year: int, event: str, session_type: str, driver1, driver2):
    with st.spinner("Generating lap time comparison..."):
        # Get lap times for both drivers
        driver1_laps = get_driver_lap_times(
            year, event, session_type, driver1["Driver"]
        )
        driver2_laps = get_driver_lap_times(
            year, event, session_type, driver2["Driver"]
        )

        if driver1_laps.empty or driver2_laps.empty:
            st.error("Unable to fetch lap times for one or both drivers")
            return

        # Convert lap times from seconds to minutes for better Y-axis display
        driver1_laps["LapTimeMinutes"] = driver1_laps["LapTimeSeconds"] / 60
        driver2_laps["LapTimeMinutes"] = driver2_laps["LapTimeSeconds"] / 60

        # Add driver name for legend
        driver1_laps["Driver"] = driver1["DisplayName"]
        driver2_laps["Driver"] = driver2["DisplayName"]

        # Get team colors
        driver1_color = get_team_color(
            team_id=(
                driver1_laps["TeamID"].iloc[0]
                if "TeamID" in driver1_laps.columns
                else None
            ),
            team_name=driver1["Team"],
        )

        driver2_color = get_team_color(
            team_id=(
                driver2_laps["TeamID"].iloc[0]
                if "TeamID" in driver2_laps.columns
                else None
            ),
            team_name=driver2["Team"],
        )

        # Create the plot
        fig = go.Figure()

        # Add traces for each driver
        fig.add_trace(
            go.Scatter(
                x=driver1_laps["LapNumber"],
                y=driver1_laps["LapTimeMinutes"],
                mode="lines+markers",
                name=driver1["DisplayName"],
                line=dict(color=driver1_color, width=2),
                marker=dict(size=8),
            )
        )

        fig.add_trace(
            go.Scatter(
                x=driver2_laps["LapNumber"],
                y=driver2_laps["LapTimeMinutes"],
                mode="lines+markers",
                name=driver2["DisplayName"],
                line=dict(color=driver2_color, width=2),
                marker=dict(size=8),
            )
        )

        # Add highlighting for personal best laps if available
        if "IsPersonalBest" in driver1_laps.columns:
            best_laps1 = driver1_laps[driver1_laps["IsPersonalBest"] == True]
            if not best_laps1.empty:
                fig.add_trace(
                    go.Scatter(
                        x=best_laps1["LapNumber"],
                        y=best_laps1["LapTimeMinutes"],
                        mode="markers",
                        name=f"{driver1['Driver']} Personal Best",
                        marker=dict(size=12, symbol="star", color=driver1_color),
                    )
                )

        if "IsPersonalBest" in driver2_laps.columns:
            best_laps2 = driver2_laps[driver2_laps["IsPersonalBest"] == True]
            if not best_laps2.empty:
                fig.add_trace(
                    go.Scatter(
                        x=best_laps2["LapNumber"],
                        y=best_laps2["LapTimeMinutes"],
                        mode="markers",
                        name=f"{driver2['Driver']} Personal Best",
                        marker=dict(size=12, symbol="star", color=driver2_color),
                    )
                )

        # Update layout for better visualization
        fig.update_layout(
            title=f"Lap Time Comparison: {driver1['Driver']} vs {driver2['Driver']}",
            xaxis_title="Lap Number",
            yaxis_title="Lap Time (minutes)",
            template="plotly_dark",
            hovermode="x unified",
            legend=dict(
                orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5
            ),
            # Format y-axis to show minutes:seconds
            yaxis=dict(tickformat=".2f"),
        )

        # Adjust x-axis to show integer lap numbers
        fig.update_xaxes(dtick=1, tickmode="linear")  # Tick every 1 lap

        # Add custom hover information
        fig.update_traces(
            hovertemplate="<b>Lap %{x}</b><br>Time: %{y:.2f} min<extra></extra>"
        )

        # Show the plot
        st.plotly_chart(fig, use_container_width=True)

        # Add table showing lap time details
        st.subheader("Lap Time Details")

        # Prepare data for table
        merged_laps = pd.merge(
            driver1_laps[["LapNumber", "LapTimeSeconds"]].rename(
                columns={"LapTimeSeconds": f"{driver1['Driver']}_Time"}
            ),
            driver2_laps[["LapNumber", "LapTimeSeconds"]].rename(
                columns={"LapTimeSeconds": f"{driver2['Driver']}_Time"}
            ),
            on="LapNumber",
            how="outer",
        )

        # Calculate gap (positive means driver1 is slower, negative means driver2 is slower)
        merged_laps["Gap"] = (
            merged_laps[f"{driver1['Driver']}_Time"]
            - merged_laps[f"{driver2['Driver']}_Time"]
        )

        # Format lap times for display
        merged_laps[f"{driver1['Driver']}_Display"] = merged_laps[
            f"{driver1['Driver']}_Time"
        ].apply(format_lap_time)
        merged_laps[f"{driver2['Driver']}_Display"] = merged_laps[
            f"{driver2['Driver']}_Time"
        ].apply(format_lap_time)
        merged_laps["Gap_Display"] = merged_laps["Gap"].apply(
            lambda x: (
                f"+{format_lap_time(abs(x))}"
                if x > 0
                else f"-{format_lap_time(abs(x))}" if x < 0 else "0.000"
            )
        )

        # Create a more readable DataFrame for display
        display_df = merged_laps[
            [
                "LapNumber",
                f"{driver1['Driver']}_Display",
                f"{driver2['Driver']}_Display",
                "Gap_Display",
            ]
        ]
        display_df.columns = [
            "Lap",
            f"{driver1['Driver']}",
            f"{driver2['Driver']}",
            "Gap",
        ]

        # Sort by lap number
        display_df = display_df.sort_values("Lap")

        # Show table
        st.dataframe(display_df, use_container_width=True)

        # Add summary stats
        st.subheader("Summary Statistics")

        # Calculate stats
        driver1_min = driver1_laps["LapTimeSeconds"].min()
        driver1_max = driver1_laps["LapTimeSeconds"].max()
        driver1_avg = driver1_laps["LapTimeSeconds"].mean()

        driver2_min = driver2_laps["LapTimeSeconds"].min()
        driver2_max = driver2_laps["LapTimeSeconds"].max()
        driver2_avg = driver2_laps["LapTimeSeconds"].mean()

        # Create columns for stats display
        stat_col1, stat_col2, stat_col3 = st.columns(3)

        with stat_col1:
            st.metric(
                label=f"{driver1['Driver']} Best Lap",
                value=format_lap_time(driver1_min),
            )
            st.metric(
                label=f"{driver2['Driver']} Best Lap",
                value=format_lap_time(driver2_min),
            )

        with stat_col2:
            st.metric(
                label=f"{driver1['Driver']} Average Lap",
                value=format_lap_time(driver1_avg),
            )
            st.metric(
                label=f"{driver2['Driver']} Average Lap",
                value=format_lap_time(driver2_avg),
            )

        with stat_col3:
            # Calculate best lap difference
            best_lap_diff = driver1_min - driver2_min
            if best_lap_diff < 0:
                best_gap = f"{driver1['Driver']} faster by {format_lap_time(abs(best_lap_diff))}"
            elif best_lap_diff > 0:
                best_gap = f"{driver2['Driver']} faster by {format_lap_time(abs(best_lap_diff))}"
            else:
                best_gap = "No difference"

            st.metric(label="Best Lap Difference", value=best_gap)

            # Calculate average lap difference
            avg_lap_diff = driver1_avg - driver2_avg
            if avg_lap_diff < 0:
                avg_gap = f"{driver1['Driver']} faster by {format_lap_time(abs(avg_lap_diff))}"
            elif avg_lap_diff > 0:
                avg_gap = f"{driver2['Driver']} faster by {format_lap_time(abs(avg_lap_diff))}"
            else:
                avg_gap = "No difference"

            st.metric(label="Average Lap Difference", value=avg_gap)


# Function to show lap time comparison
def show_lap_comparison(year: int, event: str, session_type: str):
    st.subheader("Lap Time Comparison")

    # Get available drivers
    drivers = get_available_drivers(year, event, session_type)

    if not drivers:
        st.warning(f"No driver data available for {event} {year} {session_type}")
        return

    # Initialize session state for tracking driver selections
    if "prev_driver1" not in st.session_state:
        st.session_state.prev_driver1 = None
    if "prev_driver2" not in st.session_state:
        st.session_state.prev_driver2 = None
    if "driver1_index" not in st.session_state:
        st.session_state.driver1_index = 0
    if "driver2_index" not in st.session_state:
        st.session_state.driver2_index = 1 if len(drivers) > 1 else 0

    # Create columns for driver selection
    col1, col2 = st.columns(2)

    # Create the driver option dictionaries once for both selections
    all_driver_options = {d["DisplayName"]: d for d in drivers}
    driver_display_names = list(all_driver_options.keys())

    with col1:
        # Driver 1 selector - keep track of the index
        selected_driver1_key = st.selectbox(
            "Driver 1",
            options=driver_display_names,
            index=min(st.session_state.driver1_index, len(driver_display_names) - 1),
            key="driver1",
        )

        # Update the index for next time
        st.session_state.driver1_index = driver_display_names.index(
            selected_driver1_key
        )
        driver1 = all_driver_options[selected_driver1_key]

    # Handle the case where both drivers might be the same
    # We need to ensure driver2 options exclude driver1
    driver2_options = [
        name for name in driver_display_names if name != selected_driver1_key
    ]

    # If driver1 changed to what was previously driver2
    if selected_driver1_key == st.session_state.prev_driver2:
        # Find a new driver2 that's not the same as driver1
        if driver2_options:
            # Default to the previous driver1 if it's valid
            if st.session_state.prev_driver1 in driver2_options:
                default_driver2 = st.session_state.prev_driver1
                default_index = driver2_options.index(default_driver2)
            else:
                default_index = 0
        else:
            default_index = None
    else:
        # Try to maintain the previous driver2 selection if valid
        if st.session_state.prev_driver2 in driver2_options:
            default_index = driver2_options.index(st.session_state.prev_driver2)
        elif driver2_options:
            default_index = 0
        else:
            default_index = None

    with col2:
        # If no other drivers available
        if not driver2_options:
            st.warning("No other drivers available for comparison")
            return

        # Driver 2 selector
        selected_driver2_key = st.selectbox(
            "Driver 2", options=driver2_options, index=default_index, key="driver2"
        )

        driver2 = all_driver_options[selected_driver2_key]

    # Store current selections for next comparison
    st.session_state.prev_driver1 = selected_driver1_key
    st.session_state.prev_driver2 = selected_driver2_key

    # Generate comparison if both drivers are selected
    if selected_driver1_key and selected_driver2_key:
        generate_lap_comparison(year, event, session_type, driver1, driver2)


def main():
    st.set_page_config(
        page_title="F1 Lap Time Comparison", page_icon="🏎️", layout="wide"
    )

    st.title("F1 Lap Time Comparison")
    st.markdown("Compare lap times between two drivers across all laps in a session.")

    # Add error handling container above everything
    error_container = st.empty()

    try:
        # Sidebar for session selection
        st.sidebar.header("Data Selection")

        # Get available sessions
        available_sessions = get_available_sessions()

        if not available_sessions:
            st.sidebar.warning(
                "No data available. Please check your MongoDB connection."
            )
            return

        # Initialize session state for selections if needed
        if "selected_year" not in st.session_state:
            st.session_state.selected_year = None
        if "selected_event" not in st.session_state:
            st.session_state.selected_event = None
        if "selected_session" not in st.session_state:
            st.session_state.selected_session = None

        # Select year
        year_options = list(available_sessions.keys())
        selected_year = st.sidebar.selectbox(
            "Year", year_options, index=0 if year_options else None, key="year_selector"
        )

        # Update session state for year
        if selected_year != st.session_state.selected_year:
            st.session_state.selected_year = selected_year
            # Reset dependent selections when year changes
            st.session_state.selected_event = None
            st.session_state.selected_session = None

            # Also reset driver selections when year changes
            if "prev_driver1" in st.session_state:
                st.session_state.prev_driver1 = None
            if "prev_driver2" in st.session_state:
                st.session_state.prev_driver2 = None

        # Select event based on year
        if selected_year:
            event_options = list(available_sessions[selected_year].keys())
            event_index = (
                0
                if event_options
                and st.session_state.selected_event not in event_options
                else (
                    event_options.index(st.session_state.selected_event)
                    if st.session_state.selected_event in event_options
                    else 0
                )
            )

            selected_event = st.sidebar.selectbox(
                "Grand Prix",
                event_options,
                index=event_index if event_options else None,
                key="event_selector",
            )

            # Update session state for event
            if selected_event != st.session_state.selected_event:
                st.session_state.selected_event = selected_event
                # Reset session selection when event changes
                st.session_state.selected_session = None

                # Also reset driver selections when event changes
                if "prev_driver1" in st.session_state:
                    st.session_state.prev_driver1 = None
                if "prev_driver2" in st.session_state:
                    st.session_state.prev_driver2 = None

            # Select session type based on year and event
            if selected_event:
                session_options = available_sessions[selected_year][selected_event]
                session_index = (
                    0
                    if session_options
                    and st.session_state.selected_session not in session_options
                    else (
                        session_options.index(st.session_state.selected_session)
                        if st.session_state.selected_session in session_options
                        else 0
                    )
                )

                selected_session = st.sidebar.selectbox(
                    "Session",
                    session_options,
                    index=session_index if session_options else None,
                    key="session_selector",
                )

                # Update session state
                st.session_state.selected_session = selected_session

                # Display lap comparison when all selections are made
                if selected_session:
                    show_lap_comparison(selected_year, selected_event, selected_session)

        # Sidebar for additional info
        st.sidebar.markdown("---")
        st.sidebar.info(
            """
            This application visualizes lap time data for Formula 1 drivers, allowing you to compare
            performance across all laps in a session.
            
            - Select two different drivers to compare their lap times
            - View lap-by-lap performance differences
            - See statistical summaries including best and average lap times
            """
        )

    except Exception as e:
        error_container.error(f"An error occurred: {str(e)}")
        st.stop()


if __name__ == "__main__":
    main()
