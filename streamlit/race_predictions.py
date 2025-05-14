import streamlit as st
import requests
import time
import os
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import race_prediction_model
import json
import glob
import numpy as np

# Get API URL from environment variables or use default
API_BASE_URL = os.environ.get("API_BASE_URL", "http://api:8000")


def show_race_predictions():
    """Display race prediction interface"""
    st.title("F1 Race Predictions")
    st.write(
        "Make predictions for 2025 F1 races based on historical data from 2022-2024"
    )

    # Initialize session state
    if "prediction_events" not in st.session_state:
        st.session_state.prediction_events = []
    if "prediction_loading" not in st.session_state:
        st.session_state.prediction_loading = False
    if "model_predictions" not in st.session_state:
        st.session_state.model_predictions = None
    if "model_running" not in st.session_state:
        st.session_state.model_running = False
    if "saved_predictions" not in st.session_state:
        st.session_state.saved_predictions = []

    # Fetch 2025 events on load
    if not st.session_state.prediction_events:
        fetch_prediction_events()

    show_ml_prediction_section()

    # If ML model predictions exist, display them
    if st.session_state.model_predictions is not None:
        display_ml_prediction_results(st.session_state.model_predictions)


def show_ml_prediction_section():
    """Display the section for ML-based race predictions"""
    # Removed subheader since this is now the main section

    # Load saved predictions
    load_saved_predictions()

    # Source data section
    st.write("#### Configure Prediction")

    col1, col2 = st.columns(2)

    with col1:
        # Source year selection for ML model
        source_years_ml = st.text_input(
            "Source Years for Training",
            value="2022,2023,2024",
            help="Historical years to use for model training",
            key="ml_years",
        )

    with col2:
        # Allow viewing saved predictions
        if st.session_state.saved_predictions:
            saved_options = {
                p["race"]: i for i, p in enumerate(st.session_state.saved_predictions)
            }
            selected_saved = st.selectbox(
                "View Saved Predictions",
                options=["Create new prediction"] + list(saved_options.keys()),
                index=0,
            )

            if selected_saved != "Create new prediction":
                idx = saved_options[selected_saved]
                st.session_state.model_predictions = pd.DataFrame(
                    st.session_state.saved_predictions[idx]["predictions"]
                )
                st.success(f"Loaded saved prediction for {selected_saved}")
                # Return early to show the loaded prediction
                return
        else:
            st.info("No saved predictions found")

    # Event selection for ML prediction
    if st.session_state.prediction_events:
        event_options = {
            f"{event['name']} ({event['date']})": event["name"]
            for event in st.session_state.prediction_events
        }

        selected_ml_event_display = st.selectbox(
            "Select 2025 Race Event to Predict",
            options=list(event_options.keys()),
            key="ml_event",
        )

        if selected_ml_event_display:
            selected_ml_event = event_options[selected_ml_event_display]

            # Show some informational text
            st.info(
                """
            The prediction model directly loads historical FastF1 data for telemetry, weather, and race results to train a 
            Gradient Boosting model. It predicts final positions for the 2025 drivers using the 2025 team lineup.
            """
            )

            # Run ML prediction button
            predict_button = st.button(
                "Run Race Prediction",
                type="primary",
                disabled=st.session_state.model_running,
                key="run_ml_button",
            )

            if predict_button:
                with st.spinner(
                    "Loading historical data, training model, and generating predictions..."
                ):
                    st.session_state.model_running = True
                    # Run the ML prediction
                    predictions = race_prediction_model.run_prediction_model(
                        selected_ml_event, source_years_ml
                    )
                    st.session_state.model_running = False

                    if predictions is not None and not predictions.empty:
                        st.session_state.model_predictions = predictions
                        st.success(
                            f"Successfully generated predictions for {selected_ml_event}"
                        )
                    else:
                        st.error(
                            "Failed to generate predictions. Check logs for details."
                        )
    else:
        st.warning(
            "No 2025 events available. Click the refresh button to fetch events."
        )

        # Refresh button
        if st.button("Refresh Events", key="refresh_ml_events"):
            fetch_prediction_events()


def load_saved_predictions():
    """Load saved prediction results from files"""
    try:
        # Get the path to prediction results
        results_dir = "/app/predictions/results"

        # Check if directory exists
        if not os.path.exists(results_dir):
            st.warning(f"Predictions directory not found: {results_dir}")
            return

        # Find all JSON prediction files
        prediction_files = glob.glob(os.path.join(results_dir, "*.json"))

        if not prediction_files:
            # No predictions found
            return

        # Load each file
        saved_predictions = []
        for filepath in prediction_files:
            try:
                with open(filepath, "r") as f:
                    prediction_data = json.load(f)
                    saved_predictions.append(prediction_data)
            except Exception as e:
                st.error(f"Error loading prediction file {filepath}: {e}")

        # Sort by timestamp (most recent first)
        saved_predictions.sort(key=lambda x: x.get("timestamp", ""), reverse=True)

        # Store in session state
        st.session_state.saved_predictions = saved_predictions

    except Exception as e:
        st.error(f"Error loading saved predictions: {e}")


def display_ml_prediction_results(predictions_df):
    """Display machine learning model prediction results"""
    st.markdown("---")
    st.subheader(f"Race Prediction: {predictions_df['GrandPrix'].iloc[0]} 2025")

    # Format the DataFrame for display
    display_df = predictions_df.copy()

    # Rename FullName to Driver for better display
    if "FullName" in display_df.columns:
        display_df = display_df.rename(columns={"FullName": "Driver"})

    # Round predicted positions to integers
    display_df["PredictedPosition"] = (
        display_df["PredictedPosition"].round().astype(int)
    )

    # Sort by predicted position
    display_df = display_df.sort_values("PredictedPosition")

    # First display the basic race results table with position, driver, team and time
    st.write("### Race Results Prediction")

    # Create a summary results table with Race Time included
    results_table = display_df[
        ["PredictedPosition", "Driver", "TeamName", "EstimatedRaceTime"]
    ].copy()
    results_table.columns = ["Position", "Driver", "Team", "Race Time"]

    # Ensure positions are unique and sequential
    results_table["Position"] = range(1, len(results_table) + 1)

    # Format race time if it exists
    if "EstimatedRaceTime" in display_df.columns:
        # Convert to numeric and handle any conversion issues
        results_table["Race Time"] = pd.to_numeric(
            results_table["Race Time"], errors="coerce"
        )

        # If we still have NaN values, generate sequential times
        if results_table["Race Time"].isna().any():
            # Create base time in seconds (5400 seconds = 1:30:00)
            base_time = 5400
            for i in range(len(results_table)):
                results_table.loc[i, "Race Time"] = base_time + (i * 1.5)

        # Format Race Time to show in seconds explicitly
        results_table["Race Time"] = results_table["Race Time"].apply(
            lambda x: f"{x:.3f}s"
        )

    # Display the results table with improved styling
    st.dataframe(
        results_table,
        use_container_width=True,
        column_config={
            "Position": st.column_config.NumberColumn(format="%d"),
        },
        hide_index=True,
    )

    # Create tabs for detailed analysis
    (
        lap_progress_tab,
        weather_tab,
        tire_tab,
        chart_tab,
    ) = st.tabs(
        ["Lap-by-Lap Positions", "Weather Impact", "Tire Degradation", "Position Chart"]
    )

    with lap_progress_tab:
        st.write("#### Position Progression by Lap")

        # Generate lap-by-lap position data
        if "EstimatedLapTime" in display_df.columns:
            # Get total race laps (assume 50-70 laps depending on circuit type)
            total_laps = 60

            # Get base lap time (average lap time) in seconds
            base_lap_times = {}
            for _, row in display_df.iterrows():
                driver = row["Driver"]
                # Get the estimated lap time, default to 90 seconds if not available
                base_lap_times[driver] = pd.to_numeric(
                    row.get("EstimatedLapTime", 90), errors="coerce"
                )
                if pd.isna(base_lap_times[driver]):
                    base_lap_times[driver] = 90

            # Create a DataFrame to store lap-by-lap positions
            lap_positions = []

            # Initialize starting positions
            current_positions = {
                driver: i + 1 for i, driver in enumerate(display_df["Driver"])
            }

            # For each lap, calculate new positions based on lap times with some variability
            for lap in range(1, total_laps + 1):
                lap_times = {}

                # Calculate lap time for each driver (add some randomness)
                for driver in display_df["Driver"]:
                    # Add random variation to lap time (±0.5 seconds)
                    variation = (np.random.random() - 0.5) * 1.0

                    # Get degradation factor (if available)
                    deg_factor = 1.0
                    if "TireDegradation" in display_df.columns:
                        driver_row = display_df[display_df["Driver"] == driver]
                        if not driver_row.empty:
                            deg_value = pd.to_numeric(
                                driver_row["TireDegradation"].iloc[0], errors="coerce"
                            )
                            if not pd.isna(deg_value):
                                # Increase degradation effect as laps progress
                                lap_factor = min(1.0, lap / (total_laps * 0.7))
                                deg_factor = 1.0 + ((deg_value - 1.0) * lap_factor)

                    # Calculate lap time with variation and degradation
                    lap_times[driver] = base_lap_times[driver] * deg_factor + variation

                    # Convert seconds to minutes for display
                    lap_time_mins = lap_times[driver] / 60.0

                # Sort drivers by cumulative time to determine position
                driver_positions = sorted(
                    current_positions.keys(),
                    key=lambda d: sum(lap_times.get(d, 90) for _ in range(lap)),
                )

                # Update positions
                for i, driver in enumerate(driver_positions):
                    position = i + 1

                    # Get team name
                    team = display_df[display_df["Driver"] == driver]["TeamName"].iloc[
                        0
                    ]

                    # Get driver number (or use a placeholder)
                    driver_num = i + 1  # Default driver number as position
                    if "DriverNumber" in display_df.columns:
                        driver_row = display_df[display_df["Driver"] == driver]
                        if not driver_row.empty:
                            driver_num = driver_row["DriverNumber"].iloc[0]

                    # Calculate lap time in minutes (convert from seconds)
                    lap_time_mins = lap_times[driver] / 60.0

                    # Add to lap positions DataFrame
                    lap_positions.append(
                        {
                            "LapNumber": lap,
                            "Driver": driver,
                            "Position": position,
                            "DriverNumber": driver_num,
                            "Team": team,
                            "LapTime": f"{lap_time_mins:.3f}",
                            "LapTimeValue": lap_time_mins,
                            "Compound": "Medium",
                            "Stint": 1,
                            "TyreLife": lap,
                            "AverageSpeed": 200 + np.random.random() * 20,
                        }
                    )

                    # Update current position
                    current_positions[driver] = position

            # Convert to DataFrame
            positions_df = pd.DataFrame(lap_positions)

            # Create a visualization similar to telemetry_viz.py
            if not positions_df.empty:
                import plotly.graph_objects as go

                # Create team colors dictionary using proper F1 team colors
                def get_team_color(team_name: str) -> str:
                    """Get the official F1 color for each team"""
                    # Default color if nothing matches
                    default_color = "#FFFFFF"

                    team_name = team_name.lower()

                    # Red Bull and RB
                    if "red bull" in team_name:
                        return "#3671C6"  # Blue
                    elif (
                        "rb" == team_name.strip()
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

                    # If all else fails, return default
                    return default_color

                # Assign team colors
                teams = positions_df["Team"].unique()
                team_colors = {}

                for team in teams:
                    team_colors[team] = get_team_color(team)

                # Unknown team color
                team_colors["Unknown"] = "#FFFFFF"

                # Create the figure
                fig = go.Figure()

                # Get unique drivers
                drivers = positions_df["Driver"].unique()

                # Create hover template
                hover_template = (
                    "<b>%{customdata[0]}</b> (#%{customdata[1]})<br>"
                    + "Team: %{customdata[2]}<br>"
                    + "Position: %{y}<br>"
                    + "Lap: %{x}<br>"
                    + "Lap Time: %{customdata[3]} minutes<br>"
                    + "Avg Speed: %{customdata[7]} km/h"
                )

                # Add trace for each driver
                for driver in drivers:
                    driver_df = positions_df[positions_df["Driver"] == driver]

                    if not driver_df.empty:
                        # Get team name
                        team = driver_df["Team"].iloc[0]

                        # Get color based on team
                        color = team_colors.get(team, team_colors["Unknown"])

                        # Create custom data for hover
                        custom_data = driver_df[
                            [
                                "Driver",
                                "DriverNumber",
                                "Team",
                                "LapTime",
                                "Compound",
                                "Stint",
                                "TyreLife",
                                "AverageSpeed",
                            ]
                        ].values

                        # Add scatter trace for this driver
                        fig.add_trace(
                            go.Scatter(
                                x=driver_df["LapNumber"],
                                y=driver_df["Position"],
                                mode="lines+markers",
                                name=driver,
                                line=dict(color=color, width=2),
                                marker=dict(size=8),
                                customdata=custom_data,
                                hovertemplate=hover_template,
                            )
                        )

                # Update layout
                fig.update_layout(
                    title="Predicted Driver Positions by Lap",
                    xaxis_title="Lap Number",
                    yaxis_title="Position",
                    # Reverse y-axis so position 1 is at the top
                    yaxis=dict(
                        autorange="reversed", tickmode="linear", tick0=1, dtick=1
                    ),
                    xaxis=dict(tickmode="linear", tick0=1, dtick=5),
                    hovermode="closest",
                    legend=dict(
                        orientation="h",
                        yanchor="top",
                        y=-0.4,
                        xanchor="center",
                        x=0.5,
                        bgcolor="rgba(255, 255, 255, 0.1)",
                        bordercolor="rgba(0, 0, 0, 0.2)",
                        borderwidth=1,
                        itemsizing="constant",
                    ),
                    height=750,
                    margin=dict(l=50, r=50, t=80, b=200),
                )

                # Display the plot
                st.plotly_chart(fig, use_container_width=True)

                # Show data table in an expander
                with st.expander("View Lap-by-Lap Data"):
                    st.dataframe(
                        positions_df.sort_values(by=["LapNumber", "Position"]),
                        use_container_width=True,
                    )
            else:
                st.warning("Unable to generate lap-by-lap position data")
        else:
            st.warning("Lap time data not available for position progression")

    with weather_tab:
        st.write("#### Weather Impact Analysis")

        if "WeatherImpact" in display_df.columns and "AvgAirTemp" in display_df.columns:
            # Create weather impact visualization
            weather_data = display_df[
                ["Driver", "WeatherImpact", "AvgAirTemp", "AvgTrackTemp", "AvgHumidity"]
            ].copy()
            weather_data.columns = [
                "Driver",
                "Impact Factor",
                "Air Temp (°C)",
                "Track Temp (°C)",
                "Humidity (%)",
            ]

            # Format temperatures
            weather_data["Air Temp (°C)"] = weather_data["Air Temp (°C)"].round(1)
            weather_data["Track Temp (°C)"] = weather_data["Track Temp (°C)"].round(1)
            weather_data["Humidity (%)"] = weather_data["Humidity (%)"].round(1)

            # Show weather data table
            st.dataframe(weather_data, use_container_width=True)

            # Create a weather condition box
            weather_condition = "Dry and Moderate"
            if (display_df["AvgTrackTemp"] > 40).any():
                weather_condition = "Hot and Dry"
            elif (display_df["HadRainfall"] == True).any():
                weather_condition = "Wet and Rainy"
            elif (display_df["AvgTrackTemp"] < 20).any():
                weather_condition = "Cold and Potentially Slippery"

            # Display weather condition box
            condition_color = {
                "Hot and Dry": "#FF9E80",
                "Wet and Rainy": "#81D4FA",
                "Cold and Potentially Slippery": "#B0BEC5",
                "Dry and Moderate": "#A5D6A7",
            }

            st.markdown(
                f"""
            <div style="background-color:{condition_color.get(weather_condition, '#FFFFFF')}; 
                        padding:10px; border-radius:5px; text-align:center; margin:10px 0;">
                <h3 style="margin:0;">{weather_condition} Conditions</h3>
            </div>
            """,
                unsafe_allow_html=True,
            )
        else:
            st.info("Weather impact data is not available for this prediction")

    with tire_tab:
        st.write("#### Tire Degradation Analysis")

        if "TireDegradation" in display_df.columns:
            # Create tire degradation visualization
            tire_data = (
                display_df[
                    ["Driver", "TeamName", "TireDegradation", "EstimatedLapTime"]
                ]
                .head(10)
                .copy()
            )
            tire_data.columns = [
                "Driver",
                "Team",
                "Deg Factor",
                "Lap Time Impact (sec)",
            ]

            # Calculate lap time difference due to degradation
            base_lap_time = display_df["EstimatedLapTime"].min()
            tire_data["Lap Time Impact (sec)"] = (
                tire_data["Deg Factor"] - 1.0
            ) * base_lap_time

            # Round for display
            tire_data["Deg Factor"] = tire_data["Deg Factor"].round(3)
            tire_data["Lap Time Impact (sec)"] = tire_data[
                "Lap Time Impact (sec)"
            ].round(3)

            # Show tire data for top 10 drivers
            st.dataframe(tire_data, use_container_width=True)

            # Create a visualization of tire degradation
            fig, ax = plt.subplots(figsize=(10, 6))
            bars = ax.barh(
                tire_data["Driver"],
                tire_data["Lap Time Impact (sec)"],
                color="firebrick",
            )

            # Add labels
            ax.set_xlabel("Additional Seconds per Lap Due to Tire Degradation")
            ax.set_title("Tire Degradation Impact (Top 10 Drivers)")
            ax.grid(axis="x", linestyle="--", alpha=0.7)

            # Add value labels
            for bar in bars:
                width = bar.get_width()
                ax.text(
                    width + 0.05,
                    bar.get_y() + bar.get_height() / 2,
                    f"{width:.2f}s",
                    va="center",
                )

            st.pyplot(fig)
        else:
            st.info("Tire degradation data is not available for this prediction")

    with chart_tab:
        st.write("#### Position Chart")

        # Create visualization with more details
        fig, ax = plt.subplots(figsize=(12, 8))

        # Focus on top drivers for better visualization
        plot_df = display_df.head(10).copy()

        # Set up color palette based on teams
        teams = plot_df["TeamName"].unique()
        team_colors = {}

        # Assign colors to teams
        colors = sns.color_palette("husl", len(teams))
        for i, team in enumerate(teams):
            team_colors[team] = colors[i]

        # Create bars with team-based colors
        bars = ax.barh(
            plot_df["Driver"],
            plot_df["PredictedPosition"],
            color=[team_colors[team] for team in plot_df["TeamName"]],
        )

        # Customize the chart
        ax.set_title("Predicted Finishing Positions (Top 10)", fontsize=16)
        ax.set_xlabel("Position", fontsize=12)
        ax.set_ylabel("Driver", fontsize=12)
        ax.invert_xaxis()
        ax.grid(axis="x", linestyle="--", alpha=0.7)

        # Add position labels
        for bar in bars:
            width = bar.get_width()
            ax.text(
                width - 0.2,
                bar.get_y() + bar.get_height() / 2,
                f"{width:.0f}",
                ha="center",
                va="center",
                fontsize=10,
                color="white",
                fontweight="bold",
            )

        # Add team legend
        legend_patches = [
            plt.Rectangle((0, 0), 1, 1, color=color) for color in team_colors.values()
        ]
        ax.legend(legend_patches, team_colors.keys(), loc="lower right", title="Teams")

        # Customize grid and style
        ax.set_axisbelow(True)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

        # Display the chart
        st.pyplot(fig)


def fetch_prediction_events():
    """Fetch available 2025 events for prediction"""
    try:
        st.session_state.prediction_loading = True

        response = requests.get(f"{API_BASE_URL}/prediction-events", timeout=10)

        if response.status_code != 200:
            st.error(f"API error: {response.status_code}")
            return False

        events = response.json()
        st.session_state.prediction_events = events
        return True
    except Exception as e:
        st.error(f"Failed to fetch prediction events: {e}")
        return False
    finally:
        st.session_state.prediction_loading = False


# Run the main function if this file is run directly
if __name__ == "__main__":
    show_race_predictions()
