# Grafana Dashboard Generator

Automated tool for generating and uploading Grafana dashboards for building automation systems. This tool automatically discovers RTU devices from your Grafana datasource and creates separate, customized dashboards for each device with device point mapping and automatic API deployment.

## Features

- **Auto-Device Discovery**: Automatically detects all RTU devices from Grafana PostgreSQL datasource
- **Separate Dashboards Per Device**: Creates individual dashboard for each RTU device (no dropdown selectors)
- **Device Point Mapping**: Validates and maps device points from configuration
- **Direct API Upload**: Automatically uploads dashboards to Grafana using basic authentication
- **Organized Output**: All generated files saved to `output/` folder (auto-created)
- **Updated Occupancy Status**: Proper 3-state occupancy mapping (Local Control/Occupied/Unoccupied)
- **Multiple Visualizations**: Gauges, stats, time series with color-coded thresholds
- **Response Logging**: Saves API upload responses to JSON files for audit trails
- **Creative Dashboard Design**: Temperature gauges, equipment status indicators, setpoint displays

## Prerequisites

- Python 3.7+
- Access to a Grafana instance with PostgreSQL datasource configured
- Grafana admin credentials

## Installation

1. Clone or download this repository: 
```bash
git clone https://github.com/RoshanLKini/aems-grafana-automation.git
cd aems-grafana-automation
```
2. Install required Python packages:
```bash
pip install requests urllib3
```

## Configuration

### config.ini

Create or edit `config.ini` with the following sections:

```ini
[dashboard]
campus = PNNL
building = ROB
output-dir = output
timezone = America/Los_Angeles

[device_mapping]
effective_zone_temperature_setpoint = EffectiveZoneTemperatureSetPoint
first_stage_heating = FirstStageHeating
occupancy_command = OccupancyCommand
occupied_cooling_setpoint = OccupiedCoolingSetPoint
occupied_heating_setpoint = OccupiedHeatingSetPoint
outdoor_air_temperature = OutdoorAirTemperature
supply_fan_status = SupplyFanStatus
building_power = Watts
zone_humidity = ZoneHumidity
zone_temperature = ZoneTemperature
weather_air_temperature = air_temperature

[grafana]
url = https://your-grafana-server.com/grafana
username = admin
password = your_password
verify_ssl = false
```

#### Configuration Parameters

**[dashboard] Section:**
- `campus`: Campus identifier (e.g., PNNL)
- `building`: Building identifier (e.g., ROB)
- `output-dir`: Directory for generated JSON files (default: output)
- `timezone`: Timezone for dashboards (default: America/Los_Angeles)

**[device_mapping] Section:**
- Maps internal point names (left) to actual device point names (right)
- Used for validation and ensuring consistency across dashboards

**[grafana] Section:**
- `url`: Full URL to your Grafana instance
- `username`: Grafana username (requires admin or editor role)
- `password`: Grafana password
- `verify_ssl`: Set to `false` for self-signed certificates (default: false)

## Usage

### Generate and Upload Dashboards

```bash
python generate_dashboards.py
```

This will:
1. Load configuration from `config.ini`
2. Connect to Grafana API
3. Auto-detect PostgreSQL datasource
4. **Query and discover all RTU devices from Grafana**
5. Load dashboard templates (`rtu_overview.json`, `site_overview.json`)
6. **Generate separate dashboard for each device discovered**
7. Validate device points against mapping
8. Upload all dashboards to Grafana
9. Save API responses to timestamped JSON file in `output/` folder

### Output Files

The script generates the following files in the `output/` folder:

**Per-Device RTU Dashboards:**
- `{CAMPUS}_{BUILDING}_{DEVICE}_RTU_Overview.json` - Individual dashboard for each RTU
  - Example: `PNNL_ROB_rtu01_RTU_Overview.json`
  - Example: `PNNL_ROB_rtu02_RTU_Overview.json`
  - Example: `PNNL_ROB_rtu03_RTU_Overview.json`

**Site Overview:**
- `{CAMPUS}_{BUILDING}_Site_Overview.json` - Building-wide dashboard

**Upload Responses:**
- `{CAMPUS}_{BUILDING}_upload_response_{timestamp}.json` - API upload results with device count

## Dashboard Templates

### RTU Overview Dashboard (Per Device)

Each RTU device gets its own dedicated dashboard with real-time data:

**Temperature & Humidity Section:**
- Zone Temperature (gauge with color thresholds: 60-80°F)
- Zone Humidity (gauge with optimal range: 30-50%)
- Outdoor Air Temperature (gauge with weather-based colors)

**Setpoints Section:**
- Heating Setpoint (warm colors: red → orange → green)
- Cooling Setpoint (cool colors: green → yellow → blue)

**Equipment Status Section:**
- Equipment Stage (1st Stage Heating: OFF/HEATING)
- Supply Fan (OFF/RUNNING)
- **Occupancy Status** (1=Local Control, 2=Occupied, 3=Unoccupied)

**Power Consumption:**
- Time series graph showing power usage in kW

**Historical Trends:**
- Full-width time series with all metrics for trend analysis

**Note:** Each device gets its own dashboard - no dropdown selector needed!

### Site Overview Dashboard

Provides building-wide overview with multiple data points.

## Device Points

The following device points are supported (configured in `[device_mapping]`):

| Config Key | Device Point Name |
|------------|-------------------|
| `zone_temperature` | ZoneTemperature |
| `zone_humidity` | ZoneHumidity |
| `outdoor_air_temperature` | OutdoorAirTemperature |
| `occupied_heating_setpoint` | OccupiedHeatingSetPoint |
| `occupied_cooling_setpoint` | OccupiedCoolingSetPoint |
| `first_stage_heating` | FirstStageHeating |
| `supply_fan_status` | SupplyFanStatus |
| `occupancy_command` | OccupancyCommand |
| `building_power` | Watts |
| `effective_zone_temperature_setpoint` | EffectiveZoneTemperatureSetPoint |
| `weather_air_temperature` | air_temperature |

## API Response Format

Upload responses are saved with the following structure:

```json
{
  "upload_time": "2025-11-18T12:27:07.008484",
  "grafana_url": "https://your-grafana-server.com/grafana",
  "folder_id": 0,
  "devices_count": 4,
  "responses": [
    {
      "dashboard": "RTU Overview - rtu01",
      "device": "rtu01",
      "success": true,
      "message": "Dashboard created successfully",
      "data": {
        "id": 56,
        "slug": "pnnl-rob-rtu01-overview-2025-11-18-122705",
        "status": "success",
        "uid": "c44cd669-a0ce-4eaf-8fc4-dd5b158cba98",
        "url": "/grafana/d/c44cd669-a0ce-4eaf-8fc4-dd5b158cba98/...",
        "version": 1
      },
      "timestamp": "2025-11-18T12:27:06.331763"
    },
    {
      "dashboard": "RTU Overview - rtu02",
      "device": "rtu02",
      "success": true,
      "message": "Dashboard created successfully",
      "data": {...},
      "timestamp": "2025-11-18T12:27:06.953149"
    }
  ]
}
```

## Logging

The script uses Python's logging module with INFO level by default:

- `INFO`: Normal operation messages (connections, generation, uploads)
- `WARNING`: Non-critical issues (missing mappings, unused points)
- `ERROR`: Critical errors (connection failures, missing datasources)

Logs are output to the console. To save logs to a file, redirect output:

```bash
python generate_dashboards.py > dashboard_generation.log 2>&1
```

## Error Handling

The script performs validation and will exit with an error if:

- Grafana configuration is missing from config.ini
- Cannot connect to Grafana API
- No PostgreSQL datasource found in Grafana
- Dashboard template files are missing

Each error provides specific guidance on how to fix the issue.

## Troubleshooting

### Connection Failed

Problem: ERROR: Cannot connect to Grafana

Solution:
1. Verify Grafana URL is correct in `config.ini`
2. Check username and password are valid
3. Ensure Grafana server is running and accessible
4. Check network connectivity

### No PostgreSQL Datasource

Problem: ERROR: No PostgreSQL datasource available

Solution:
1. Log in to Grafana
2. Go to Configuration → Data Sources
3. Add a PostgreSQL datasource
4. Configure connection to your database
5. Re-run the script

### SSL Certificate Errors

Problem: SSL verification errors with self-signed certificates

Solution:
Set verify_ssl = false in the [grafana] section of config.ini

### Device Point Warnings

Problem: WARNING: Points in dashboard not in device_mapping

Solution:
Add the missing points to the `[device_mapping]` section in `config.ini`

## Security Considerations

- Store config.ini securely (contains passwords)
- Add config.ini to .gitignore to avoid committing credentials
- Use environment variables for sensitive data in production
- Enable SSL verification (verify_ssl = true) when using valid certificates
- Use service accounts with minimal required permissions

## Topic Structure

The script expects PostgreSQL topics in the format:
```
{campus}/{building}/{device}/{metric}
```

Example: `PNNL/ROB/rtu01/ZoneTemperature`

## Customization

### Adding New Dashboards

1. Create a new JSON template file
2. Add a generation function similar to `generate_rtu_overview()`
3. Update `main()` to call your generation function
4. Add device mappings to `config.ini`

### Modifying Colors and Thresholds

Edit the template JSON files:
- `rtu_overview.json` - RTU dashboard template
- `site_overview.json` - Site dashboard template

Thresholds are defined in the `fieldConfig.defaults.thresholds.steps` array.

## License

This project is provided as-is for building automation dashboard generation.

## Support

For issues or questions:
1. Check the troubleshooting section above
2. Review log output for specific error messages
3. Verify configuration in `config.ini`

## Version History

- **v2.0** - Device auto-discovery and separate dashboards per device
  - Auto-discover devices from Grafana PostgreSQL datasource
  - Create separate dashboard for each RTU device
  - Updated occupancy status mappings (1/2/3 instead of 0/1)
  - Output files organized in `output/` folder
  - Removed interactive generator (functionality consolidated)
- **v1.4** - Improved dashboard design with creative visualizations
- **v1.3** - Enhanced error handling and validation
- **v1.2** - Added API response logging
- **v1.1** - Added device mapping validation
- **v1.0** - Initial release with RTU and Site Overview dashboards
