# Grafana Dashboard Generator

Automated tool for generating and uploading Grafana dashboards for building automation systems. This tool creates customized RTU (Rooftop Unit) and Site Overview dashboards with device point mapping and automatic API deployment.

## Features

- Automated Dashboard Generation: Creates dashboards from templates with customized campus/building prefixes
- Device Point Mapping: Validates and maps device points from configuration
- Direct API Upload: Automatically uploads dashboards to Grafana using basic authentication
- Validation: Checks device points against configured mappings
- Multiple Visualizations: Gauges, stats, time series with color-coded thresholds
- Response Logging: Saves API upload responses to JSON files for audit trails
- Creative Dashboard Design: Temperature gauges, equipment status indicators, setpoint displays

## Prerequisites

- Python 3.7+
- Access to a Grafana instance with PostgreSQL datasource configured
- Grafana admin credentials

## Installation

1. Clone or download this repository
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
output-dir = .
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
- `output-dir`: Directory for generated JSON files (default: .)
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
4. Load dashboard templates (`rtu_overview.json`, `site_overview.json`)
5. Generate customized dashboards
6. Validate device points against mapping
7. Upload dashboards to Grafana
8. Save API responses to timestamped JSON file

### Output Files

The script generates the following files:

- `{CAMPUS}_{BUILDING}_RTU_Overview.json` - RTU dashboard for UI import
- `{CAMPUS}_{BUILDING}_RTU_Overview_import.json` - RTU dashboard for API import
- `{CAMPUS}_{BUILDING}_Site_Overview.json` - Site dashboard for UI import
- `{CAMPUS}_{BUILDING}_Site_Overview_import.json` - Site dashboard for API import
- `{CAMPUS}_{BUILDING}_upload_response_{timestamp}.json` - API upload results

Example: `PNNL_ROB_RTU_Overview.json`

## Dashboard Templates

### RTU Overview Dashboard

Displays real-time data for a single RTU (Rooftop Unit):

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
- Occupancy Status (UNOCCUPIED/OCCUPIED)

**Power Consumption:**
- Time series graph showing power usage in kW

**Historical Trends:**
- Full-width time series with all metrics for trend analysis

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
  "upload_time": "2025-11-17T10:32:53.384657",
  "grafana_url": "https://your-grafana-server.com/grafana",
  "folder_id": 0,
  "responses": [
    {
      "dashboard": "RTU Overview",
      "success": true,
      "message": "Dashboard created successfully",
      "data": {
        "id": 44,
        "slug": "pnnl-rob-rtu-overview-2025-11-17-103252",
        "status": "success",
        "uid": "e90590f3-485b-43bd-a31c-667993ad14a0",
        "url": "/grafana/d/e90590f3-485b-43bd-a31c-667993ad14a0/...",
        "version": 1
      },
      "timestamp": "2025-11-17T10:32:52.917207"
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

- v1.0 - Initial release with RTU and Site Overview dashboards
- v1.1 - Added device mapping validation
- v1.2 - Added API response logging
- v1.3 - Enhanced error handling and validation
- v1.4 - Improved dashboard design with creative visualizations
