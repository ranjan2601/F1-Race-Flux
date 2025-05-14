import os
import streamlit as st
import requests
import time
import json
import telemetry_viz
import race_results
import driver_simulation
import lap_comparison
import track_speed_heatmap
import race_predictions

# Set page config
st.set_page_config(
    page_title="F1 RaceFlux",
    page_icon="🏎️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Get API URL from environment variables or use default
API_BASE_URL = os.environ.get("API_BASE_URL", "http://api:8000")

# Custom styling for the app
st.markdown(
    """
<style>
    .main-title {
        text-align: center;
        font-size: 2.5rem;
        margin-bottom: 1.5rem;
        color: #e10600;
    }
    .card {
        background-color: #1a1a1a;  /* Dark background to match the theme */
        border-radius: 5px;
        padding: 1rem;
        margin-bottom: 1rem;
        border: 1px solid #333;
        color: white;
    }
    .card-title {
        font-size: 1.2rem;
        font-weight: bold;
        margin-bottom: 0.5rem;
        color: white;
    }
    .status-message {
        background-color: #1a1a1a;
        padding: 0.5rem;
        border-radius: 5px;
        margin-top: 0.5rem;
        color: #e6f7ff;
        border: 1px solid #1890ff;
    }
    .success-message {
        background-color: #1a1a1a;
        color: #2e7d32;
        padding: 0.5rem;
        border-radius: 5px;
        margin-top: 0.5rem;
        border: 1px solid #2e7d32;
    }
    .warning-message {
        background-color: #1a1a1a;
        color: #b86e00;
        padding: 0.5rem;
        border-radius: 5px;
        margin-top: 0.5rem;
        border: 1px solid #b86e00;
    }
    /* Remove any default padding/margin from Streamlit containers */
    .block-container {
        padding-top: 1rem;
        padding-bottom: 1rem;
        padding-left: 1rem;
        padding-right: 1rem;
    }
    /* Adjust column containers */
    div[data-testid="column"] {
        padding: 0 !important;
        margin: 0 !important;
    }
    /* Hide empty elements */
    .element-container:empty {
        display: none !important;
        margin: 0 !important;
        padding: 0 !important;
        height: 0 !important;
    }
    /* Customize selectbox appearance */
    .stSelectbox [data-baseweb="select"] {
        background-color: #2a2a2a;
        border-color: #444;
    }
    .stSelectbox [data-baseweb="select"]:hover {
        border-color: #666;
    }
    /* Remove streamlit branding if needed */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
</style>
""",
    unsafe_allow_html=True,
)

# Initialize session state variables
if "available_races" not in st.session_state:
    st.session_state.available_races = []
if "available_sessions" not in st.session_state:
    st.session_state.available_sessions = []
if "fetch_status" not in st.session_state:
    st.session_state.fetch_status = ""
if "loading" not in st.session_state:
    st.session_state.loading = False
if "data_processed" not in st.session_state:
    st.session_state.data_processed = False
if "data_exists" not in st.session_state:
    st.session_state.data_exists = False
if "collection_counts" not in st.session_state:
    st.session_state.collection_counts = {}
if "status_message" not in st.session_state:
    st.session_state.status_message = None
if "last_refresh" not in st.session_state:
    st.session_state.last_refresh = time.time()
if "processing_started" not in st.session_state:
    st.session_state.processing_started = False
if "container_status" not in st.session_state:
    st.session_state.container_status = None
if "show_processing_section" not in st.session_state:
    st.session_state.show_processing_section = False
if "previous_counts" not in st.session_state:
    st.session_state.previous_counts = {}
# Initialize telemetry visualization session state variables
if "telemetry_data" not in st.session_state:
    st.session_state.telemetry_data = None
if "simulation_speed" not in st.session_state:
    st.session_state.simulation_speed = 1.0
if "simulation_running" not in st.session_state:
    st.session_state.simulation_running = False
if "simulation_current_lap" not in st.session_state:
    st.session_state.simulation_current_lap = 1
if "max_lap" not in st.session_state:
    st.session_state.max_lap = 1
# Add a mode selector to session state
if "mode" not in st.session_state:
    st.session_state.mode = "Data Visualization"


# Helper functions for API calls
def fetch_available_races():
    """Fetch all available races from the API"""
    try:
        st.session_state.loading = True

        response = requests.get(f"{API_BASE_URL}/available-races", timeout=10)

        if response.status_code != 200:
            error_message = f"API error: {response.status_code}"
            try:
                error_detail = response.json().get("detail", "No details available")
                error_message += f" - {error_detail}"
            except:
                error_message += " - Could not parse error details"

            st.error(error_message)
            return False

        races = response.json()
        st.session_state.available_races = races
        return True
    except requests.exceptions.ConnectionError:
        st.error(
            f"Failed to connect to API at {API_BASE_URL}. Check if API service is running."
        )
        return False
    except requests.exceptions.Timeout:
        st.error(f"API request timed out. The API service might be overloaded.")
        return False
    except Exception as e:
        st.error(f"Failed to fetch available races: {e}")
        return False
    finally:
        st.session_state.loading = False


def fetch_sessions(year, race_name):
    """Fetch available sessions for a specific race"""
    try:
        st.session_state.loading = True

        # Skip fetching sessions for anything that starts with "Pre-Season" to avoid errors
        if race_name.startswith("Pre-Season"):
            st.warning("Session data not available for Pre-Season events")
            st.session_state.available_sessions = []
            return True

        response = requests.get(f"{API_BASE_URL}/sessions/{year}/{race_name}")
        if response.status_code != 200:
            error_message = f"API error: {response.status_code}"
            try:
                error_detail = response.json().get("detail", "No details available")
                error_message += f" - {error_detail}"
            except:
                error_message += " - Could not parse error details"

            st.error(error_message)
            return False

        data = response.json()
        st.session_state.available_sessions = data["sessions"]
        return True
    except Exception as e:
        st.error(f"Failed to fetch sessions: {e}")
        return False
    finally:
        st.session_state.loading = False


def fetch_session_data(year, race_name, session_key):
    """Trigger data processing for a specific session"""
    try:
        st.session_state.loading = True

        # Clear any previous status messages
        st.session_state.status_message = None
        st.session_state.fetch_status = "Checking for existing data..."

        payload = {"year": year, "event": race_name, "session": session_key}

        response = requests.post(f"{API_BASE_URL}/fetch-race-data", json=payload)

        if response.status_code != 200:
            st.session_state.status_message = f"API error: {response.status_code}"
            return False

        result = response.json()

        # Always show the processing section after a fetch is triggered
        st.session_state.show_processing_section = True

        # Check if data already exists
        if result.get("status") == "exists":
            st.session_state.fetch_status = "Data already exists in database"
            st.session_state.data_processed = True
            st.session_state.data_exists = True
            st.session_state.collection_counts = result.get("counts", {})
            st.session_state.previous_counts = result.get("counts", {}).copy()
            st.session_state.status_message = (
                "success:Using existing data from database - no processing needed"
            )
            return True
        # Check if container is already running
        elif result.get("status") == "already_running":
            st.session_state.fetch_status = "Processing is already running"
            st.session_state.data_processed = True
            st.session_state.data_exists = False
            st.session_state.processing_started = True
            st.session_state.container_status = "running"
            if "container_id" in result:
                st.session_state.container_id = result.get("container_id")
            st.session_state.status_message = (
                "info:Data stream is already being processed - no need to start again"
            )
            return True

        # Data is being processed
        st.session_state.fetch_status = result.get(
            "message", "Processing data through Kafka pipeline"
        )
        st.session_state.data_processed = True
        st.session_state.data_exists = False
        st.session_state.processing_started = True
        st.session_state.container_status = "running"
        st.session_state.status_message = (
            "info:Data stream initiated to Kafka pipeline - processing in progress"
        )

        # Store the container ID if it was returned
        if "container_id" in result:
            st.session_state.container_id = result.get("container_id")

        return True
    except Exception as e:
        st.session_state.status_message = f"Error: {str(e)}"
        return False
    finally:
        st.session_state.loading = False


def check_processing_status(year, race_name, session_key):
    """Poll the API to check if data processing is complete"""
    try:
        payload = {"year": year, "event": race_name, "session": session_key}

        # Use the check-processing-status endpoint
        response = requests.post(
            f"{API_BASE_URL}/check-processing-status", json=payload
        )

        if response.status_code != 200:
            return None

        result = response.json()

        # Save the container status
        if "container_status" in result:
            st.session_state.container_status = result["container_status"]

        # If data exists, processing is complete
        if result.get("status") == "complete":
            st.session_state.data_exists = True
            st.session_state.collection_counts = result.get("counts", {})
            return {
                "status": "complete",
                "message": "Data processing complete",
                "counts": result.get("counts", {}),
            }

        # Otherwise, it's still processing
        return {
            "status": "processing",
            "message": "Data processing in progress",
            "container_status": result.get("container_status", "unknown"),
        }
    except Exception as e:
        st.error(f"Error checking status: {e}")
        return None


# Main application title
st.markdown('<h1 class="main-title">F1 RaceFlux</h1>', unsafe_allow_html=True)

# Create tabs in the sidebar
with st.sidebar:
    st.header("F1 RaceFlux")

    # Create mode selector
    selected_mode = st.radio("Select Mode", ["Data Visualization", "Race Predictions"])

    # Update session state when mode changes
    if selected_mode != st.session_state.mode:
        st.session_state.mode = selected_mode
        # Force a rerun to update the UI
        st.rerun()

# Different content based on selected mode
if st.session_state.mode == "Data Visualization":
    # VISUALIZATION MODE

    # Show info about selected data if available
    if (
        "selected_year" in locals()
        and "selected_race" in locals()
        and "selected_session_name" in locals()
    ):
        with st.sidebar:
            st.markdown("---")
            st.subheader("Selected Data")
            st.write(f"**Year:** {selected_year}")
            st.write(f"**Race:** {selected_race['name']}")
            st.write(f"**Session:** {selected_session_name}")

    # Fetch races on app startup
    if not st.session_state.available_races:
        fetch_available_races()

    # Create a layout with 4 columns for the selection controls
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.markdown(
            '<div class="card-title">1. Select Year</div>', unsafe_allow_html=True
        )

        # Fixed years from 2022-2025
        years = list(range(2022, 2026))
        selected_year = st.selectbox(
            "Select a year", years, label_visibility="collapsed"
        )

        st.markdown("</div>", unsafe_allow_html=True)

    with col2:
        st.markdown(
            '<div class="card-title">2. Select Race</div>', unsafe_allow_html=True
        )

        if "selected_year" not in locals():
            st.write("Please select a year first")
        else:
            # Filter races by selected year AND exclude anything that starts with "Pre-Season"
            filtered_races = [
                race
                for race in st.session_state.available_races
                if race["year"] == selected_year
                and not race["name"].startswith("Pre-Season")
            ]

            if st.session_state.loading and not filtered_races:
                st.write("Loading races...")
            elif filtered_races:
                race_options = {f"{race['name']}": race for race in filtered_races}
                selected_race_name = st.selectbox(
                    "Select a race",
                    list(race_options.keys()),
                    label_visibility="collapsed",
                )

                # Store the selected race object
                if selected_race_name:
                    selected_race = race_options[selected_race_name]

                    # When race changes, fetch sessions
                    if selected_race and (
                        "last_selected_race" not in st.session_state
                        or st.session_state.last_selected_race != selected_race_name
                    ):
                        st.session_state.last_selected_race = selected_race_name
                        fetch_sessions(selected_year, selected_race["name"])
            else:
                st.write("No races available for this year")

                # Add a refresh button
                if st.button("Refresh Races"):
                    fetch_available_races()

        st.markdown("</div>", unsafe_allow_html=True)

    with col3:
        st.markdown(
            '<div class="card-title">3. Select Session</div>', unsafe_allow_html=True
        )

        if "selected_race" not in locals():
            st.write("Please select a race first")
        else:
            if st.session_state.loading and not st.session_state.available_sessions:
                st.write("Loading sessions...")
            elif st.session_state.available_sessions:
                session_options = {
                    session["name"]: session["key"]
                    for session in st.session_state.available_sessions
                }

                selected_session_name = st.selectbox(
                    "Select a session",
                    list(session_options.keys()),
                    label_visibility="collapsed",
                )

                # Store the selected session key
                if selected_session_name:
                    selected_session_key = session_options[selected_session_name]
            else:
                st.write("No sessions available for this race")

        st.markdown("</div>", unsafe_allow_html=True)

    with col4:
        st.markdown(
            '<div class="card-title">4. Fetch Data</div>', unsafe_allow_html=True
        )

        if "selected_session_name" not in locals():
            st.write("Please select a session first")
        else:
            fetch_button = st.button(
                "Fetch Data",
                disabled=st.session_state.loading,
                type="primary",
                use_container_width=True,
            )

            if fetch_button:
                success = fetch_session_data(
                    selected_year, selected_race["name"], selected_session_key
                )
                # After fetching, always show the processing section
                st.session_state.show_processing_section = True

            # Display single consolidated status message
            if st.session_state.status_message:
                msg_type, msg_text = st.session_state.status_message.split(":", 1)
                if msg_type == "success":
                    st.success(msg_text)
                elif msg_type == "info":
                    st.info(msg_text)
                elif msg_type == "warning":
                    st.warning(msg_text)
                else:
                    st.error(msg_text)

        st.markdown("</div>", unsafe_allow_html=True)

    # Show processing status - always show if we've ever fetched data
    if "selected_session_key" in locals() and (
        st.session_state.data_processed or st.session_state.show_processing_section
    ):
        st.markdown("---")
        st.subheader("Data Processing Pipeline")

        # Create a simple processing indicator
        processing_status = st.empty()

        if st.session_state.data_exists:
            # Show metrics for existing data
            st.markdown(
                '<div class="card-title">Collection Record Counts</div>',
                unsafe_allow_html=True,
            )

            # Create two rows of three columns for the six collections
            row1_cols = st.columns(3)
            row2_cols = st.columns(3)

            # Define the collections in the order we want to display them
            collections = [
                "telemetry",
                "car_telemetry",
                "car_position",
                "driver_info",
                "race_results",
                "weather",
            ]

            # First row of collections
            for i, col in enumerate(row1_cols):
                with col:
                    collection_name = collections[i]
                    count = st.session_state.collection_counts.get(collection_name, 0)
                    st.metric(
                        collection_name.replace("_", " ").title(),
                        f"{count:,} records",
                        delta="Available",
                    )

            # Second row of collections
            for i, col in enumerate(row2_cols):
                if i + 3 < len(collections):
                    with col:
                        collection_name = collections[i + 3]
                        count = st.session_state.collection_counts.get(
                            collection_name, 0
                        )
                        st.metric(
                            collection_name.replace("_", " ").title(),
                            f"{count:,} records",
                            delta="Available",
                        )

            # Add a refresh button to check for updated record counts
            if st.button("Refresh Record Counts"):
                if (
                    "selected_year" in locals()
                    and "selected_race" in locals()
                    and "selected_session_key" in locals()
                ):
                    status_result = check_processing_status(
                        selected_year, selected_race["name"], selected_session_key
                    )

                    if status_result and status_result.get("status") == "complete":
                        # Store previous counts for comparison
                        st.session_state.previous_counts = (
                            st.session_state.collection_counts.copy()
                        )
                        new_counts = status_result.get("counts", {})

                        # Check if counts have changed
                        if new_counts != st.session_state.previous_counts:
                            st.session_state.data_exists = True
                            st.session_state.collection_counts = new_counts
                            st.session_state.status_message = (
                                "success:Record counts refreshed - new data available!"
                            )
                            st.rerun()
                        else:
                            st.session_state.status_message = (
                                "info:No new data since last refresh"
                            )
                            st.info("No new data since last refresh")

            st.markdown("</div>", unsafe_allow_html=True)

        else:
            # Display the processing steps for new data
            processing_status.info(
                "Data is being processed through the Kafka pipeline..."
            )

            # Create progress indicators for each processing step
            st.markdown('<div class="card">', unsafe_allow_html=True)
            st.markdown(
                '<div class="card-title">Processing Status</div>',
                unsafe_allow_html=True,
            )

            col1, col2, col3 = st.columns(3)

            with col1:
                kafka_status = st.empty()
                container_status = st.session_state.container_status or "unknown"
                if container_status == "running":
                    kafka_status.metric("Kafka Producer", "Active", delta="Running")
                else:
                    kafka_status.metric(
                        "Kafka Producer", container_status.capitalize(), delta=None
                    )

            with col2:
                spark_status = st.empty()
                if container_status == "running":
                    spark_status.metric("Spark Processor", "Active", delta="Running")
                else:
                    spark_status.metric(
                        "Spark Processor",
                        (
                            "Waiting"
                            if container_status == "unknown"
                            else container_status.capitalize()
                        ),
                        delta=None,
                    )

            with col3:
                mongo_status = st.empty()
                if container_status == "running":
                    mongo_status.metric("MongoDB Writer", "Active", delta="Running")
                else:
                    mongo_status.metric(
                        "MongoDB Writer",
                        (
                            "Waiting"
                            if container_status == "unknown"
                            else container_status.capitalize()
                        ),
                        delta=None,
                    )

            # Add a refresh button and auto-refresh logic
            refresh_col, auto_refresh_col = st.columns(2)

            with refresh_col:
                if st.button("Check Processing Status"):
                    if (
                        "selected_year" in locals()
                        and "selected_race" in locals()
                        and "selected_session_key" in locals()
                    ):
                        status_result = check_processing_status(
                            selected_year, selected_race["name"], selected_session_key
                        )

                        if status_result and status_result.get("status") == "complete":
                            # Store previous counts for comparison
                            st.session_state.previous_counts = (
                                st.session_state.collection_counts.copy()
                                if hasattr(st.session_state, "collection_counts")
                                else {}
                            )
                            new_counts = status_result.get("counts", {})

                            # Check if counts have changed
                            if new_counts != st.session_state.previous_counts:
                                st.session_state.data_exists = True
                                st.session_state.collection_counts = new_counts
                                st.session_state.status_message = (
                                    "success:Data processing complete!"
                                )
                                st.rerun()
                            else:
                                # No new records, don't refresh UI
                                st.session_state.data_exists = True
                                st.info(
                                    "Processing complete, but no new data available yet"
                                )
                        elif status_result:
                            st.session_state.container_status = status_result.get(
                                "container_status", "unknown"
                            )
                            st.info(
                                f"Processing status: {status_result.get('message')} (Container: {st.session_state.container_status})"
                            )
                        else:
                            st.warning("Could not determine processing status")

            with auto_refresh_col:
                auto_refresh = st.checkbox(
                    "Auto-refresh status (every 10s)", value=True
                )

            # Auto-refresh logic for checking processing status
            if auto_refresh and st.session_state.processing_started:
                current_time = time.time()
                if (
                    current_time - st.session_state.last_refresh > 10
                ):  # 10 second refresh interval
                    st.session_state.last_refresh = current_time

                    if (
                        "selected_year" in locals()
                        and "selected_race" in locals()
                        and "selected_session_key" in locals()
                    ):
                        status_result = check_processing_status(
                            selected_year, selected_race["name"], selected_session_key
                        )

                        if status_result and status_result.get("status") == "complete":
                            # Store previous counts for comparison
                            st.session_state.previous_counts = (
                                st.session_state.collection_counts.copy()
                                if hasattr(st.session_state, "collection_counts")
                                else {}
                            )
                            new_counts = status_result.get("counts", {})

                            # Check if counts have changed
                            if new_counts != st.session_state.previous_counts:
                                st.session_state.data_exists = True
                                st.session_state.collection_counts = new_counts
                                st.session_state.status_message = (
                                    "success:Data processing complete!"
                                )
                                st.rerun()
                            else:
                                # No new records, don't refresh UI
                                st.session_state.data_exists = True
                        elif status_result:
                            st.session_state.container_status = status_result.get(
                                "container_status", "unknown"
                            )

            st.markdown("</div>", unsafe_allow_html=True)

    # TELEMETRY VISUALIZATION SECTION
    # Show this section when fetch has been initiated or data exists
    if (
        (st.session_state.show_processing_section or st.session_state.data_exists)
        and "selected_year" in locals()
        and "selected_race" in locals()
        and "selected_session_name" in locals()
    ):
        # Call the visualization function from telemetry_viz.py
        telemetry_viz.show_telemetry_visualization(
            year=selected_year,
            event=selected_race["name"],
            session_type=selected_session_name,
        )

    # RACE RESULTS SECTION
    # Only show for races when processing has started or data exists
    if (
        (st.session_state.show_processing_section or st.session_state.data_exists)
        and "selected_year" in locals()
        and "selected_race" in locals()
        and "selected_session_name" in locals()
        and selected_session_name == "Race"
    ):

        # Call the race results function from race_results.py
        race_results.show_race_results(year=selected_year, event=selected_race["name"])

    # LAP COMPARISON SECTION
    # Show when processing has started or data exists
    if (
        (st.session_state.show_processing_section or st.session_state.data_exists)
        and "selected_year" in locals()
        and "selected_race" in locals()
        and "selected_session_name" in locals()
    ):
        # Call the lap comparison function
        lap_comparison.show_lap_comparison(
            year=selected_year,
            event=selected_race["name"],
            session_type=selected_session_name,
        )

    # TRACK SPEED HEATMAP SECTION
    # Show when processing has started or data exists
    if (
        (st.session_state.show_processing_section or st.session_state.data_exists)
        and "selected_year" in locals()
        and "selected_race" in locals()
        and "selected_session_name" in locals()
    ):
        # Call the track speed heatmap function
        track_speed_heatmap.show_track_speed_heatmap(
            year=selected_year,
            event=selected_race["name"],
            session_type=selected_session_name,
        )

    # DRIVER SIMULATION SECTION
    # Show when processing has started or data exists
    if (
        (st.session_state.show_processing_section or st.session_state.data_exists)
        and "selected_year" in locals()
        and "selected_race" in locals()
        and "selected_session_name" in locals()
    ):
        # Call the driver simulation function
        driver_simulation.show_driver_simulation(
            year=selected_year,
            event=selected_race["name"],
            session_type=selected_session_name,
        )

elif st.session_state.mode == "Race Predictions":
    # PREDICTION MODE - Completely separate interface
    race_predictions.show_race_predictions()

# Add footer
st.markdown("---")
st.caption("F1 RaceFlux | Built with Streamlit | Data provided by FastF1")
