# OMJET Log Analyzer

An advanced desktop application for analyzing ArduPilot flight logs (.bin, .log, .tlog).

![Python](https://img.shields.io/badge/Python-3.12+-blue.svg)
![PySide6](https://img.shields.io/badge/PySide6-6.6+-green.svg)
![License](https://img.shields.io/badge/License-MIT-yellow.svg)

## Features

- **Log Parsing**: Supports .bin (dataflash), .log (text), and .tlog (telemetry) formats
- **Interactive Maps**: GPS track visualization with basemap support
- **Multi-Graph Display**: Up to 3 synchronized graphs with multiple curves
- **Timeline Navigation**: Visual time scrubber with altitude backdrop
- **Playback Mode**: Animate through the flight log at various speeds
- **Parameter Viewer**: Browse and analyze flight parameters
- **Event Detection**: Automatic event highlighting (arm/disarm, modes, etc.)
- **RC Input Display**: Real-time RC channel visualization
- **Attitude Panel**: Roll/Pitch/Yaw gauges with speed and altitude
- **Motor/Servo Monitor**: PWM output visualization
- **Dark/Light Theme**: User-selectable color scheme

## Installation

### From Release (Windows)
1. Download the latest `OMJET_Log_Analyzer.exe` from the [Releases](https://github.com/yourusername/omjet-log-analyzer/releases) page
2. Run the executable - no installation required

### From Source
```bash
# Clone the repository
git clone https://github.com/yourusername/omjet-log-analyzer.git
cd omjet-log-analyzer

# Create virtual environment
python -m venv .venv
.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # Linux/Mac

# Install dependencies
pip install -r requirements.txt

# Run the application
python main.py
```

## Usage

1. Launch the application
2. Click **File → Open Log...** or use Ctrl+O
3. Select an ArduPilot log file (.bin, .log, or .tlog)
4. Browse the loaded data:
   - Use the **Message Tree** to select fields for graphing
   - Switch to **Graph** tab to view selected parameters
   - Use **Map** tab for GPS track visualization
   - Check **Events** for flight event markers

### Graph Controls
- Check fields in the message tree to add them to graphs
- Use the dropdown to select which graph (1, 2, or 3) receives new curves
- Click and drag on graphs to select time ranges
- Use the timeline at the bottom to scrub through the flight

### Playback
- Click **▶ Play** to animate through the log
- Adjust speed with the dropdown (x1, x2, x4)
- Click **⏹ Stop** to reset to the beginning

## Building from Source

```bash
# Install PyInstaller
pip install pyinstaller

# Build executable
pyinstaller main.spec --clean

# Find the executable in dist/OMJET_Log_Analyzer/
```

## Supported Log Formats

| Format | Extension | Description |
|--------|-----------|-------------|
| DataFlash | .bin | Binary log from SD card |
| Text Log | .log | ASCII text format |
| Telemetry | .tlog | MavLink telemetry log |

## Dependencies

- **PySide6** (>=6.6) - Qt GUI framework
- **pymavlink** (>=2.4.41) - MavLink protocol support
- **pyqtgraph** (>=0.13) - Fast plotting
- **numpy** (>=1.26) - Numerical operations
- **pandas** (>=2.1) - Data manipulation

## License

MIT License - see LICENSE file for details

## Contributing

Contributions welcome! Please open an issue or submit a pull request.
