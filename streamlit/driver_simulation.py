import os
import streamlit as st
import pandas as pd
import numpy as np
import pymongo
import json
import time
from typing import Dict, Any, Optional, List, Tuple
import streamlit.components.v1 as components

# MongoDB connection settings
MONGO_URI = os.environ.get("MONGO_URI", "mongodb://mongodb:27017/")
DB_NAME = os.environ.get("DB_NAME", "f1db")


# MongoDB connection function
@st.cache_resource
def get_mongodb_client():
    return pymongo.MongoClient(MONGO_URI)


# Function to get driver information and create mappings
def get_driver_mappings(
    year: int, event: str, session_type: str
) -> Tuple[Dict, Dict, Dict]:
    try:
        client = get_mongodb_client()
        db = client[DB_NAME]

        # Get driver info
        driver_info_collection = db["driver_info"]
        query = {"Year": year, "GrandPrix": event, "SessionType": session_type}

        driver_info = list(driver_info_collection.find(query))

        # If no results, try with more general query
        if not driver_info:
            query = {"Year": year, "GrandPrix": event}
            driver_info = list(driver_info_collection.find(query))

        # Create mappings
        code_to_number = {}
        number_to_code = {}
        driver_details = {}

        for driver in driver_info:
            code = driver.get("Driver")
            number = driver.get("DriverNumber")

            if code and number:
                code_to_number[code] = number
                number_to_code[number] = code
                driver_details[code] = driver

        return code_to_number, number_to_code, driver_details

    except Exception as e:
        st.error(f"Error fetching driver mappings: {e}")
        return {}, {}, {}


# Function to get available drivers for a session
def get_available_drivers(year: int, event: str, session_type: str) -> List[Dict]:
    try:
        client = get_mongodb_client()
        db = client[DB_NAME]

        # Get driver mappings
        _, number_to_code, driver_details = get_driver_mappings(
            year, event, session_type
        )

        # Get all drivers from driver_info
        available_drivers = []

        # First check driver_info collection
        driver_info_collection = db["driver_info"]
        query = {"Year": year, "GrandPrix": event, "SessionType": session_type}

        drivers_from_info = list(driver_info_collection.find(query))

        if drivers_from_info:
            for driver in drivers_from_info:
                available_drivers.append(
                    {
                        "Driver": driver.get("Driver"),
                        "DriverNumber": driver.get("DriverNumber"),
                        "FullName": driver.get("FullName"),
                        "TeamName": driver.get("TeamName"),
                        "TeamID": driver.get("TeamID", 0),
                        "DisplayName": f"{driver.get('Driver')} - {driver.get('FullName')}",
                    }
                )
        else:
            # If no drivers found in driver_info, try telemetry collection
            telemetry_collection = db["car_telemetry"]
            telemetry_query = {
                "Year": year,
                "GrandPrix": event,
                "SessionType": session_type,
            }

            # Get distinct driver numbers from telemetry
            driver_numbers = telemetry_collection.distinct("Driver", telemetry_query)

            # Also check position collection
            position_collection = db["car_position"]
            position_query = {
                "Year": year,
                "GrandPrix": event,
                "SessionType": session_type,
            }

            position_numbers = position_collection.distinct("Driver", position_query)

            # Combine all driver numbers
            all_numbers = list(set(driver_numbers + position_numbers))

            # Convert numbers to driver codes using the mapping
            for number in all_numbers:
                code = number_to_code.get(number, number)

                if code in driver_details:
                    # We have details for this driver
                    driver = driver_details[code]
                    available_drivers.append(
                        {
                            "Driver": code,
                            "DriverNumber": number,
                            "FullName": driver.get("FullName"),
                            "TeamName": driver.get("TeamName"),
                            "TeamID": driver.get("TeamID", 0),
                            "DisplayName": f"{code} - {driver.get('FullName')}",
                        }
                    )
                else:
                    # No details, use what we have
                    available_drivers.append(
                        {
                            "Driver": code,
                            "DriverNumber": number,
                            "FullName": f"Driver {number}",
                            "TeamName": None,
                            "TeamID": 0,
                            "DisplayName": f"Driver #{number}",
                        }
                    )

        return available_drivers

    except Exception as e:
        st.error(f"Error fetching available drivers: {e}")
        return []


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

        # Sauber
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


def fetch_driver_data(
    year: int, event: str, session_type: str, driver_info: Dict
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    try:
        client = get_mongodb_client()
        db = client[DB_NAME]

        # Get the driver code and number
        driver_code = driver_info["Driver"]
        driver_number = driver_info["DriverNumber"]

        # Fetch telemetry data using driver number
        telemetry_collection = db["car_telemetry"]
        telemetry_query = {
            "Year": year,
            "GrandPrix": event,
            "SessionType": session_type,
            "Driver": driver_number,
        }

        telemetry_data = list(telemetry_collection.find(telemetry_query))

        # Fetch position data using driver number
        position_collection = db["car_position"]
        position_query = {
            "Year": year,
            "GrandPrix": event,
            "SessionType": session_type,
            "Driver": driver_number,
        }

        position_data = list(position_collection.find(position_query))

        # Fetch lap data for this driver
        lap_collection = db["telemetry"]
        lap_query = {
            "Year": year,
            "GrandPrix": event,
            "SessionType": session_type,
            "DriverNumber": driver_number,
        }

        lap_data = list(
            lap_collection.find(
                lap_query, {"LapNumber": 1, "LapStartTime": 1, "Time": 1, "Date": 1}
            )
        )

        # Convert to DataFrames
        if telemetry_data:
            telemetry_df = pd.DataFrame(telemetry_data)
            if "_id" in telemetry_df.columns:
                telemetry_df = telemetry_df.drop("_id", axis=1)

            # Sort telemetry data by LapNumber and Time
            if "LapNumber" in telemetry_df.columns and "Time" in telemetry_df.columns:
                telemetry_df = telemetry_df.sort_values(["LapNumber", "Time"])
            elif "Time" in telemetry_df.columns:
                telemetry_df = telemetry_df.sort_values("Time")
        else:
            telemetry_df = pd.DataFrame()

        if position_data:
            position_df = pd.DataFrame(position_data)
            if "_id" in position_df.columns:
                position_df = position_df.drop("_id", axis=1)

            # Sort position data by LapNumber and Time
            if "LapNumber" in position_df.columns and "Time" in position_df.columns:
                position_df = position_df.sort_values(["LapNumber", "Time"])
            elif "Time" in position_df.columns:
                position_df = position_df.sort_values("Time")
        else:
            position_df = pd.DataFrame()

        if lap_data:
            lap_df = pd.DataFrame(lap_data)
            if "_id" in lap_df.columns:
                lap_df = lap_df.drop("_id", axis=1)

            # Sort lap data by LapNumber
            if "LapNumber" in lap_df.columns:
                lap_df = lap_df.sort_values("LapNumber")
        else:
            lap_df = pd.DataFrame()

        return telemetry_df, position_df, lap_df

    except Exception as e:
        st.error(f"Error fetching driver data: {e}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()


# Function to get the total number of laps for a race
def get_total_race_laps(year: int, event: str, session_type: str) -> int:
    try:
        client = get_mongodb_client()
        db = client[DB_NAME]

        # First try to get it from the telemetry collection
        telemetry_collection = db["telemetry"]
        query = {"Year": year, "GrandPrix": event, "SessionType": session_type}

        # Find max lap number across all drivers
        pipeline = [
            {"$match": query},
            {"$group": {"_id": None, "maxLap": {"$max": "$LapNumber"}}},
        ]

        result = list(telemetry_collection.aggregate(pipeline))

        if result and "maxLap" in result[0]:
            return result[0]["maxLap"]

        race_laps = {
            "Saudi Arabian Grand Prix": 50,
            "Bahrain Grand Prix": 57,
            "Australian Grand Prix": 58,
            "Japanese Grand Prix": 53,
            "Chinese Grand Prix": 56,
            "Miami Grand Prix": 57,
            "Emilia Romagna Grand Prix": 63,
            "Monaco Grand Prix": 78,
            "Canadian Grand Prix": 70,
            "Spanish Grand Prix": 66,
            "Austrian Grand Prix": 71,
            "British Grand Prix": 52,
            "Hungarian Grand Prix": 70,
            "Belgian Grand Prix": 44,
            "Dutch Grand Prix": 72,
            "Italian Grand Prix": 53,
            "Azerbaijan Grand Prix": 51,
            "Singapore Grand Prix": 62,
            "United States Grand Prix": 56,
            "Mexico City Grand Prix": 71,
            "São Paulo Grand Prix": 71,
            "Las Vegas Grand Prix": 50,
            "Qatar Grand Prix": 57,
            "Abu Dhabi Grand Prix": 58,
        }

        return race_laps.get(event, 50)

    except Exception as e:
        st.error(f"Error fetching total race laps: {e}")
        return 50


# Function to render the F1 simulation component
def render_f1_simulation_component(
    position_data, telemetry_data, driver_info, total_laps
):
    try:
        # Clean DataFrames to ensure they can be converted to JSON
        if not position_data.empty:
            position_df = position_data.copy()

            # Convert any MongoDB ObjectId to string (if present)
            if "_id" in position_df.columns:
                position_df = position_df.drop("_id", axis=1)

            # Handle NaN values and make sure all values are JSON serializable
            position_df = position_df.fillna(0)
            position_json = position_df.to_json(orient="records", date_format="iso")
        else:
            position_json = "[]"

        if not telemetry_data.empty:
            telemetry_df = telemetry_data.copy()

            # Convert any MongoDB ObjectId to string (if present)
            if "_id" in telemetry_df.columns:
                telemetry_df = telemetry_df.drop("_id", axis=1)

            # Handle NaN values and make sure all values are JSON serializable
            telemetry_df = telemetry_df.fillna(0)
            telemetry_json = telemetry_df.to_json(orient="records", date_format="iso")
        else:
            telemetry_json = "[]"

        # Get team color
        team_id = driver_info.get("TeamID", 0)
        team_name = driver_info.get("TeamName", "")
        team_color = get_team_color(team_id, team_name)

        # Create HTML/JS for component
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>F1 Telemetry Simulator</title>
            <style>
                body {{
                    margin: 0;
                    padding: 0;
                    font-family: Arial, sans-serif;
                    background-color: transparent;
                }}
                
                #simulator-container {{
                    display: flex;
                    flex-direction: column;
                    background-color: #1a1a1a;
                    border-radius: 8px;
                    padding: 16px;
                    color: white;
                    max-width: 100%;
                    margin: 0;
                }}
                
                .sim-title {{
                    font-size: 1.2rem;
                    font-weight: bold;
                    margin-bottom: 16px;
                    text-align: center;
                }}
                
                .controls-row {{
                    display: flex;
                    justify-content: space-between;
                    margin-bottom: 16px;
                    flex-wrap: wrap;
                    gap: 10px;
                }}
                
                .control-group {{
                    display: flex;
                    align-items: center;
                }}
                
                .play-button {{
                    background-color: #e10600;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    padding: 8px 16px;
                    cursor: pointer;
                    font-weight: bold;
                    margin-right: 8px;
                }}
                
                .reset-button {{
                    background-color: #333;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    padding: 8px 16px;
                    cursor: pointer;
                    font-weight: bold;
                }}
                
                .speed-select {{
                    background-color: #222;
                    color: white;
                    border: 1px solid #444;
                    border-radius: 4px;
                    padding: 6px;
                    margin-left: 8px;
                }}
                
                .canvas-container {{
                    width: 100%;
                    height: 400px;
                    background-color: #111;
                    border-radius: 6px;
                    overflow: hidden;
                    position: relative;
                    margin-bottom: 16px;
                }}
                
                #track-canvas {{
                    width: 100%;
                    height: 100%;
                }}
                
                .slider-container {{
                    width: 100%;
                    margin: 16px 0;
                }}
                
                .frame-slider {{
                    width: 100%;
                    background-color: #333;
                    -webkit-appearance: none;
                    height: 6px;
                    border-radius: 3px;
                    outline: none;
                }}
                
                .frame-slider::-webkit-slider-thumb {{
                    -webkit-appearance: none;
                    appearance: none;
                    width: 16px;
                    height: 16px;
                    border-radius: 50%;
                    background: #e10600;
                    cursor: pointer;
                }}
                
                .dashboard {{
                    display: flex;
                    flex-wrap: wrap;
                    gap: 8px;
                    margin-top: 16px;
                }}
                
                .metric-card {{
                    background-color: #222;
                    border-radius: 4px;
                    padding: 12px;
                    flex: 1;
                    min-width: 100px;
                    text-align: center;
                }}
                
                .metric-title {{
                    font-size: 12px;
                    color: #aaa;
                    margin-bottom: 4px;
                }}
                
                .metric-value {{
                    font-size: 22px;
                    font-weight: bold;
                }}
                
                .speed-value {{
                    color: #3498db;
                }}
                
                .rpm-value {{
                    color: #e74c3c;
                }}
                
                .gear-value {{
                    color: #2ecc71;
                }}
                
                .throttle-value {{
                    color: #f39c12;
                }}
                
                .lap-value {{
                    color: #f1c40f;
                }}

                
                .progress-bar {{
                    width: 100%;
                    height: 8px;
                    background-color: #444;
                    border-radius: 4px;
                    margin-top: 8px;
                    overflow: hidden;
                }}
                
                .progress-value {{
                    height: 100%;
                    background-color: #e10600;
                    border-radius: 4px;
                    width: 0%;
                }}
                

                
                .loading-overlay {{
                    position: absolute;
                    top: 0;
                    left: 0;
                    width: 100%;
                    height: 100%;
                    background-color: rgba(0,0,0,0.7);
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    font-size: 20px;
                    color: white;
                    z-index: 100;
                }}
                
                /* Driver name display */
                .driver-info {{
                    display: flex;
                    align-items: center;
                    margin-bottom: 12px;
                }}
                
                .driver-number {{
                    background-color: {team_color};
                    color: white;
                    font-weight: bold;
                    padding: 4px 8px;
                    border-radius: 4px;
                    margin-right: 10px;
                    font-size: 16px;
                    min-width: 28px;
                    text-align: center;
                }}
                
                .driver-name {{
                    font-size: 16px;
                    font-weight: bold;
                }}
                
                .team-name {{
                    font-size: 14px;
                    opacity: 0.8;
                    margin-left: 10px;
                }}
            </style>
        </head>
        <body>
            <div id="simulator-container">
                <div class="driver-info">
                    <div class="driver-number">{driver_info.get('DriverNumber', '')}</div>
                    <div class="driver-name">{driver_info.get('Driver', '')} - {driver_info.get('FullName', '')}</div>
                    <div class="team-name">{driver_info.get('TeamName', '')}</div>
                </div>
                
                <div class="controls-row">
                    <div class="control-group">
                        <button id="play-button" class="play-button">Play</button>
                        <button id="reset-button" class="reset-button">Reset</button>
                    </div>
                    <div class="control-group">
                        <label for="speed-select">Speed:</label>
                        <select id="speed-select" class="speed-select">
                            <option value="0.25">0.25x</option>
                            <option value="0.5" selected>0.5x</option>
                            <option value="1.0">1.0x</option>
                            <option value="2.0">2.0x</option>
                            <option value="4.0">4.0x</option>
                            <option value="8.0">8.0x</option>
                        </select>
                    </div>
                </div>
                
                <div class="canvas-container">
                    <canvas id="track-canvas"></canvas>
                    <div id="loading-overlay" class="loading-overlay">Processing data...</div>
                </div>
                
                <div class="slider-container">
                    <input type="range" id="frame-slider" class="frame-slider" min="0" value="0" step="1">
                </div>
                
                <div class="dashboard">
                    <div class="metric-card">
                        <div class="metric-title">SPEED</div>
                        <div id="speed-value" class="metric-value speed-value">0 km/h</div>
                    </div>
                    
                    <div class="metric-card">
                        <div class="metric-title">RPM</div>
                        <div id="rpm-value" class="metric-value rpm-value">0</div>
                    </div>
                    
                    <div class="metric-card">
                        <div class="metric-title">GEAR</div>
                        <div id="gear-value" class="metric-value gear-value">0</div>
                    </div>
                    
                    <div class="metric-card">
                        <div class="metric-title">THROTTLE</div>
                        <div id="throttle-value" class="metric-value throttle-value">0%</div>
                    </div>
                    
                    
                    <div class="metric-card">
                        <div class="metric-title">LAP</div>
                        <div id="lap-value" class="metric-value lap-value">1 / {total_laps}</div>
                        <div class="progress-bar">
                            <div id="progress-value" class="progress-value"></div>
                        </div>
                    </div>
                </div>
            </div>
            
            <script>
                // Store data from Python
                const positionData = {position_json};
                const telemetryData = {telemetry_json};
                const totalLaps = {total_laps};
                const teamColor = "{team_color}";
                
                // State variables
                let currentFrame = 0;
                let isPlaying = false;
                let speedFactor = 0.5;
                let animationId = null;
                let currentTelemetry = {{
                    Speed: 0,
                    RPM: 0,
                    nGear: 1,
                    Throttle: 0,
                    Brake: 0,
                    DRS: 0,
                    LapNumber: 1
                }};
                
                // Get DOM elements
                const canvas = document.getElementById('track-canvas');
                const ctx = canvas.getContext('2d');
                const playButton = document.getElementById('play-button');
                const resetButton = document.getElementById('reset-button');
                const speedSelect = document.getElementById('speed-select');
                const frameSlider = document.getElementById('frame-slider');
                const loadingOverlay = document.getElementById('loading-overlay');
                
                // Dashboard elements
                const speedValue = document.getElementById('speed-value');
                const rpmValue = document.getElementById('rpm-value');
                const gearValue = document.getElementById('gear-value');
                const throttleValue = document.getElementById('throttle-value');
                const lapValue = document.getElementById('lap-value');
                const progressValue = document.getElementById('progress-value');
                
                // Debug function - helpful for diagnosing issues
                function debug(message) {{
                    console.log("F1 Simulator: " + message);
                }}
                
                // Initialize the canvas and data
                function initialize() {{
                    debug("Initializing simulator");
                    
                    // Set canvas size
                    resizeCanvas();
                    window.addEventListener('resize', resizeCanvas);
                    
                    // Set up initial dashboard values
                    updateDashboard({{
                        Speed: 0,
                        RPM: 0,
                        nGear: 1,
                        Throttle: 0,
                        Brake: 0,
                        DRS: 0,
                        LapNumber: 1
                    }});
                    
                    // Check if we have data
                    if (positionData && positionData.length) {{
                        debug(`Position data loaded: ${{positionData.length}} points`);
                        
                        // Set up the frame slider range
                        frameSlider.max = positionData.length - 1;
                        
                        // Process the track data to find boundaries
                        processTrackData();
                        
                        // Draw the initial track
                        drawTrack(0);
                        
                        // Hide loading overlay
                        loadingOverlay.style.display = 'none';
                    }} else {{
                        debug("No position data available");
                        loadingOverlay.textContent = 'No position data available';
                    }}
                    
                    // Set up event listeners
                    playButton.addEventListener('click', togglePlay);
                    resetButton.addEventListener('click', resetSimulation);
                    speedSelect.addEventListener('change', handleSpeedChange);
                    frameSlider.addEventListener('input', handleFrameChange);
                }}
                
                // Resize canvas to fit container
                function resizeCanvas() {{
                    const container = canvas.parentElement;
                    canvas.width = container.clientWidth;
                    canvas.height = container.clientHeight;
                    
                    debug(`Canvas resized to ${{canvas.width}}x${{canvas.height}}`);
                    
                    // If we have already processed data, redraw the track
                    if (window.trackBoundaries) {{
                        drawTrack(currentFrame);
                    }}
                }}
                
               // Process track data to find boundaries and structure
function processTrackData() {{
    if (!positionData || !positionData.length) {{
        debug("Cannot process track data - no position data");
        return;
    }}
    
    debug("Processing track data");
    
    // Calculate track boundaries directly from position data
    // This matches the approach in the heatmap code
    let xValues = positionData.map(d => parseFloat(d.X));
    let yValues = positionData.map(d => parseFloat(d.Y));
    
    // Filter out any NaN values
    xValues = xValues.filter(x => !isNaN(x));
    yValues = yValues.filter(y => !isNaN(y));
    
    if (xValues.length === 0 || yValues.length === 0) {{
        debug("Cannot determine track boundaries - invalid coordinates");
        return;
    }}
    
    const xMin = Math.min(...xValues);
    const xMax = Math.max(...xValues);
    const yMin = Math.min(...yValues);
    const yMax = Math.max(...yValues);
    
    debug(`Track boundaries: X(${{xMin}} to ${{xMax}}), Y(${{yMin}} to ${{yMax}})`);
    
    // Add padding consistent with the heatmap code (10%)
    const xPadding = Math.abs(xMin * 0.1);
    const yPadding = Math.abs(yMin * 0.1);
    
    // Store the boundaries matching the heatmap calculation
    window.trackBoundaries = {{
        xMin: xMin - xPadding,
        xMax: xMax + xPadding,
        yMin: yMin - yPadding,
        yMax: yMax + yPadding
    }};
    
    // We don't need lap boundaries for this visualization approach
    window.lapBoundaries = [];
}}

// Draw the track and car on the canvas
function drawTrack(frameIndex) {{
    if (!canvas || !ctx || !positionData || !positionData.length || !window.trackBoundaries) {{
        debug("Cannot draw track - missing required data");
        return;
    }}
    
    // Clear the canvas
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    
    const boundaries = window.trackBoundaries;
    
    // Calculate scale factors
    const xRange = boundaries.xMax - boundaries.xMin;
    const yRange = boundaries.yMax - boundaries.yMin;
    
    const scaleX = (canvas.width - 40) / xRange;
    const scaleY = (canvas.height - 40) / yRange;
    
    // Choose the smaller scale to keep aspect ratio
    const scale = Math.min(scaleX, scaleY);
    
    // Calculate centering offsets
    const offsetX = (canvas.width - xRange * scale) / 2;
    const offsetY = (canvas.height - yRange * scale) / 2;
    
    // Function to transform coordinates
    const transformX = (x) => (parseFloat(x) - boundaries.xMin) * scale + offsetX;
    const transformY = (y) => canvas.height - ((parseFloat(y) - boundaries.yMin) * scale + offsetY);
    
    // Draw a single track outline in black
    ctx.strokeStyle = '#222222'; // Dark gray, almost black track
    ctx.lineWidth = 6;
    ctx.beginPath();
    
    let validStartFound = false;
    
    // Find first valid point to start
    for (let i = 0; i < positionData.length; i++) {{
        if (!isNaN(parseFloat(positionData[i].X)) && !isNaN(parseFloat(positionData[i].Y))) {{
            ctx.moveTo(transformX(positionData[i].X), transformY(positionData[i].Y));
            validStartFound = true;
            break;
        }}
    }}
    
    if (validStartFound) {{
        // Draw a single continuous line, skipping invalid points
        for (let i = 1; i < positionData.length; i++) {{
            if (!isNaN(parseFloat(positionData[i].X)) && !isNaN(parseFloat(positionData[i].Y))) {{
                ctx.lineTo(transformX(positionData[i].X), transformY(positionData[i].Y));
            }}
        }}
    }}
    
    ctx.stroke();
    
    // Only draw start/finish line with a small, subtle white marker
    if (positionData.length > 0 && validStartFound) {{
        // Find a valid start point
        let startPoint = positionData[0];
        for (let i = 0; i < Math.min(10, positionData.length); i++) {{
            if (!isNaN(parseFloat(positionData[i].X)) && !isNaN(parseFloat(positionData[i].Y))) {{
                startPoint = positionData[i];
                break;
            }}
        }}
        
        // Draw a small white dot for the start line
        ctx.fillStyle = 'white';
        ctx.beginPath();
        ctx.arc(transformX(startPoint.X), transformY(startPoint.Y), 4, 0, 2 * Math.PI);
        ctx.fill();
    }}
    
    // Draw current car position in team color (the only color)
    if (frameIndex < positionData.length) {{
        const currentPos = positionData[Math.floor(frameIndex)];
        
        // Draw car as a circle in team color
        if (!isNaN(parseFloat(currentPos.X)) && !isNaN(parseFloat(currentPos.Y))) {{
            // Filled circle in team color
            ctx.fillStyle = teamColor;
            ctx.beginPath();
            ctx.arc(transformX(currentPos.X), transformY(currentPos.Y), 8, 0, 2 * Math.PI);
            ctx.fill();
            
            // White border for better visibility
            ctx.strokeStyle = 'white';
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.arc(transformX(currentPos.X), transformY(currentPos.Y), 8, 0, 2 * Math.PI);
            ctx.stroke();
            
            // Add DRS indicator if active (subtle white ring)
            const hasDRS = getCurrentTelemetry(frameIndex).DRS > 0;
            if (hasDRS) {{
                ctx.strokeStyle = 'rgba(255, 255, 255, 0.6)';
                ctx.lineWidth = 1.5;
                ctx.beginPath();
                ctx.arc(transformX(currentPos.X), transformY(currentPos.Y), 12, 0, 2 * Math.PI);
                ctx.stroke();
            }}
        }}
    }}
}}
                // Find closest telemetry data for a frame
                function getCurrentTelemetry(frameIndex) {{
                    if (!positionData || !positionData.length || !telemetryData || !telemetryData.length) {{
                        return {{
                            Speed: 0,
                            RPM: 0,
                            nGear: 1,
                            Throttle: 0,
                            Brake: 0,
                            DRS: 0,
                            LapNumber: 1
                        }};
                    }}
                    
                    const frame = Math.floor(frameIndex);
                    if (frame >= positionData.length) {{
                        return telemetryData[telemetryData.length - 1] || {{
                            Speed: 0,
                            RPM: 0,
                            nGear: 1,
                            Throttle: 0,
                            Brake: 0,
                            DRS: 0,
                            LapNumber: 1
                        }};
                    }}
                    
                    const positionPoint = positionData[frame];
                    
                    // Use proportional index as fallback
                    const proportion = frame / positionData.length;
                    const telemetryIdx = Math.min(
                        Math.floor(proportion * telemetryData.length),
                        telemetryData.length - 1
                    );
                    
                    return telemetryData[telemetryIdx];
                }}
                
                // Calculate lap progress
                function calculateLapProgress(frameIndex) {{
                    if (!positionData || !positionData.length || !window.lapBoundaries || !window.lapBoundaries.length) {{
                        return 0;
                    }}
                    
                    const frame = Math.floor(frameIndex);
                    let currentLap = null;
                    
                    for (const lap of window.lapBoundaries) {{
                        if (frame >= lap.start && frame <= lap.end) {{
                            currentLap = lap;
                            break;
                        }}
                    }}
                    
                    if (!currentLap) return 0;
                    
                    const lapRange = currentLap.end - currentLap.start;
                    if (lapRange <= 0) return 0;
                    
                    return (frame - currentLap.start) / lapRange;
                }}
                
                // Get current lap number
                function getCurrentLap(frameIndex) {{
                    if (!positionData || !positionData.length) return 1;
                    
                    const frame = Math.floor(frameIndex);
                    if (frame < positionData.length && positionData[frame].hasOwnProperty('LapNumber')) {{
                        return positionData[frame].LapNumber;
                    }}
                    
                    if (window.lapBoundaries && window.lapBoundaries.length) {{
                        for (const lap of window.lapBoundaries) {{
                            if (frame >= lap.start && frame <= lap.end) {{
                                return lap.lap;
                            }}
                        }}
                    }}
                    
                    return 1;
                }}
                
                // Update dashboard display with telemetry values
                function updateDashboard(telemetry) {{
                    // Update speed
                    const speed = Math.round(telemetry.Speed || 0);
                    speedValue.textContent = `${{speed}} km/h`;
                    
                    // Update RPM
                    const rpm = Math.round(telemetry.RPM || 0);
                    rpmValue.textContent = rpm;
                    
                    // Update gear
                    const gear = telemetry.nGear || 1;
                    gearValue.textContent = gear;
                    
                    // Update throttle
                    const throttle = Math.round(telemetry.Throttle || 0);
                    throttleValue.textContent = `${{throttle}}%`;
                    
                    // Update lap info
                    const lap = telemetry.LapNumber || getCurrentLap(currentFrame);
                    lapValue.textContent = `${{lap}} / ${{totalLaps}}`;
                    
                    // Update lap progress
                    const progress = calculateLapProgress(currentFrame);
                    progressValue.style.width = `${{progress * 100}}%`;
                }}
                
                // Toggle play/pause
                function togglePlay() {{
                    isPlaying = !isPlaying;
                    playButton.textContent = isPlaying ? 'Pause' : 'Play';
                    
                    if (isPlaying) {{
                        // If at the end, restart
                        if (currentFrame >= positionData.length - 1) {{
                            currentFrame = 0;
                        }}
                        
                        // Start animation loop
                        animate();
                    }} else {{
                        // Stop animation
                        if (animationId) {{
                            cancelAnimationFrame(animationId);
                            animationId = null;
                        }}
                    }}
                }}
                
                // Animation loop
                function animate() {{
                    // Stop if we're at the end
                    if (currentFrame >= positionData.length - 1) {{
                        isPlaying = false;
                        playButton.textContent = 'Play';
                        return;
                    }}
                    
                    // Update frame based on speed factor
                    currentFrame += speedFactor;
                    
                    // Update UI elements
                    frameSlider.value = Math.floor(currentFrame);
                    
                    // Get current telemetry and update dashboard
                    const telemetry = getCurrentTelemetry(currentFrame);
                    updateDashboard(telemetry);
                    
                    // Draw current frame
                    drawTrack(currentFrame);
                    
                    // Continue animation loop
                    animationId = requestAnimationFrame(animate);
                }}
                
                // Reset simulation
                function resetSimulation() {{
                    // Stop animation if playing
                    if (isPlaying) {{
                        isPlaying = false;
                        playButton.textContent = 'Play';
                        if (animationId) {{
                            cancelAnimationFrame(animationId);
                            animationId = null;
                        }}
                    }}
                    
                    // Reset frame to beginning
                    currentFrame = 0;
                    frameSlider.value = 0;
                    
                    // Reset dashboard
                    const telemetry = getCurrentTelemetry(0);
                    updateDashboard(telemetry);
                    
                    // Redraw track
                    drawTrack(0);
                }}
                
                // Handle speed change
                function handleSpeedChange() {{
                    speedFactor = parseFloat(speedSelect.value);
                }}
                
                // Handle frame slider change
                function handleFrameChange() {{
                    // Get new frame from slider
                    currentFrame = parseInt(frameSlider.value);
                    
                    // Update dashboard with current telemetry
                    const telemetry = getCurrentTelemetry(currentFrame);
                    updateDashboard(telemetry);
                    
                    // Redraw track
                    drawTrack(currentFrame);
                }}
                
                // Initialize when document is ready
                document.addEventListener('DOMContentLoaded', initialize);
                
                // If already loaded, initialize now
                if (document.readyState === 'complete' || document.readyState === 'interactive') {{
                    initialize();
                }}
            </script>
        </body>
        </html>
        """

        # Render the HTML component
        components.html(html_content, height=700, scrolling=True)

    except Exception as e:
        st.error(f"Error rendering F1 simulation component: {e}")


# Main function to show the driver simulation
def show_driver_simulation(year: int, event: str, session_type: str):
    # Initialize session state variables
    if "driver_data" not in st.session_state:
        st.session_state.driver_data = None
    if "simulation_running" not in st.session_state:
        st.session_state.simulation_running = False
    if "selected_driver" not in st.session_state:
        st.session_state.selected_driver = None
    if "frame_index" not in st.session_state:
        st.session_state.frame_index = 0

    st.markdown("---")
    st.subheader("Driver Simulation")

    # Get available drivers
    available_drivers = get_available_drivers(year, event, session_type)

    if not available_drivers:
        st.warning(f"No driver data available for {event} {year} {session_type}")
        return

    # Create columns for controls
    col1, col2, col3 = st.columns([2, 1, 1])

    with col1:
        # Driver selector
        driver_options = {d["DisplayName"]: d for d in available_drivers}
        selected_driver_key = st.selectbox(
            "Select Driver",
            options=list(driver_options.keys()),
            index=0 if driver_options else None,
        )

        if selected_driver_key:
            st.session_state.selected_driver = driver_options[selected_driver_key]

    with col2:
        # Speed factor selector
        speed_factor = st.select_slider(
            "Simulation Speed",
            options=[0.25, 0.5, 1.0, 2.0, 4.0, 6.0, 8.0, 10.0],
            value=0.5,
        )

    with col3:
        # Load data button
        load_button = st.button("Load Data", use_container_width=True, type="primary")

        if load_button and st.session_state.selected_driver:
            with st.spinner("Loading driver data..."):
                driver = st.session_state.selected_driver
                telemetry_df, position_df, lap_df = fetch_driver_data(
                    year, event, session_type, driver
                )

                if not telemetry_df.empty and not position_df.empty:
                    # Get total race laps for this event
                    total_race_laps = get_total_race_laps(year, event, session_type)

                    # Store the sorted data
                    st.session_state.driver_data = {
                        "telemetry": telemetry_df,
                        "position": position_df,
                        "driver": st.session_state.selected_driver,
                        "total_laps": total_race_laps,
                        "lap_data": lap_df,
                    }

                    # Reset the frame index
                    st.session_state.frame_index = 0

                    st.success(f"Loaded data for driver {driver['Driver']}")
                else:
                    if telemetry_df.empty:
                        st.error(
                            f"No telemetry data available for driver {driver['Driver']} (#{driver['DriverNumber']})"
                        )
                    if position_df.empty:
                        st.error(
                            f"No position data available for driver {driver['Driver']} (#{driver['DriverNumber']})"
                        )

    if st.session_state.driver_data:
        driver_data = st.session_state.driver_data
        position_df = driver_data["position"]
        telemetry_df = driver_data["telemetry"]
        driver_info = driver_data["driver"]
        total_laps = driver_data.get("total_laps", 1)

        # Use our new component for smooth rendering
        render_f1_simulation_component(
            position_df, telemetry_df, driver_info, total_laps
        )
    else:
        st.info("No data loaded. Please select a driver and click 'Load Data'.")
