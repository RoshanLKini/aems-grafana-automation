"""
Grafana Dashboard Generator
Automates generation of Grafana dashboards using templates and config.ini
Supports both file export and direct API upload to Grafana with basic authentication
"""

import json
import configparser
from datetime import datetime
from copy import deepcopy
import os
import requests
import urllib3
import getpass
import logging
from requests.auth import HTTPBasicAuth

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s: %(message)s'
)


def get_variable_values(grafana_api, datasource_uid, campus, building):
    """
    Query Grafana to get all device values from the PostgreSQL datasource
    Returns list of device names
    """
    try:
        # Query to get all RTU devices
        query = f"select topic_name from topics where topic_name like '{campus}/{building}/%/ZoneTemperature'"
        
        # Use Grafana datasource query API
        payload = {
            "queries": [{
                "datasource": {"type": "postgres", "uid": datasource_uid},
                "rawSql": query,
                "format": "table"
            }]
        }
        
        response = requests.post(
            f'{grafana_api.url}/api/ds/query',
            auth=grafana_api.auth,
            headers=grafana_api.headers,
            json=payload,
            verify=grafana_api.verify_ssl,
            timeout=30
        )
        
        if response.status_code == 200:
            data = response.json()
            devices = []
            
            # Extract device names from topic paths
            if 'results' in data:
                for result_key in data['results']:
                    result = data['results'][result_key]
                    if 'frames' in result:
                        for frame in result['frames']:
                            if 'data' in frame and 'values' in frame['data']:
                                for values in frame['data']['values']:
                                    for topic_name in values:
                                        # Extract device name from topic: campus/building/device/point
                                        parts = topic_name.split('/')
                                        if len(parts) >= 3:
                                            device = parts[2]
                                            if device not in devices:
                                                devices.append(device)
            
            return sorted(devices)
        else:
            logging.error(f"Failed to query devices: {response.status_code}")
            return []
            
    except Exception as e:
        logging.error(f"Error querying devices: {e}")
        return []


def load_config(config_file='config.ini'):
    """Load configuration from INI file"""
    config = configparser.ConfigParser()
    config.read(config_file)
    
    # Try [dashboard] section first, fallback to DEFAULT
    section = 'dashboard' if config.has_section('dashboard') else 'DEFAULT'
    
    result = {
        'campus': config.get(section, 'campus', fallback='PNNL'),
        'building': config.get(section, 'building', fallback='ROB'),
        'gateway_address': config.get(section, 'gateway-address', fallback=''),
        'prefix': config.get(section, 'prefix', fallback=''),
        'output_dir': config.get(section, 'output-dir', fallback='output'),
        'timezone': config.get(section, 'timezone', fallback='America/Los_Angeles')
    }
    
    # Load device mapping if available
    #TODO: here we must get data from device registry
    if config.has_section('device_mapping'):
        result['device_mapping'] = dict(config.items('device_mapping'))
        logging.info(f"Loaded {len(result['device_mapping'])} device mappings from config")
    else:
        result['device_mapping'] = {}
        logging.warning("No device_mapping section found in config.ini")
    
    return result


def load_template(template_file):
    """Load dashboard template JSON file"""
    with open(template_file, 'r', encoding='utf-8') as f:
        return json.load(f)


def replace_topic_prefix(content, old_prefix, new_prefix):
    """Replace topic name prefix in JSON content"""
    content_str = json.dumps(content)
    content_str = content_str.replace(old_prefix, new_prefix)
    return json.loads(content_str)


def apply_device_mapping(content, device_mapping):
    """Apply device point name mapping to dashboard content"""
    if not device_mapping:
        logging.warning("No device mapping provided, skipping validation")
        return content
    
    content_str = json.dumps(content)
    
    # Extract all point names used in the dashboard
    import re
    used_points = set(re.findall(r'/([A-Za-z0-9_]+)(?:\'|\s)', content_str))
    
    # Get mapped point names (values from config)
    mapped_points = set(device_mapping.values())
    
    # Find points used in dashboard but not in mapping
    unmapped_points = used_points - mapped_points - {
        'topics', 'data', 'meter', 'air_temperature', 'Watts'  # Known non-device points
    }
    
    if unmapped_points:
        logging.warning(f"Points in dashboard not in device_mapping: {sorted(unmapped_points)}")
    
    # Find mapped points not used in dashboard
    unused_mappings = mapped_points - used_points
    if unused_mappings:
        logging.info(f"Mapped points not used in this dashboard: {sorted(unused_mappings)}")
    
    return content


def create_dashboard_for_device(template, config, datasource_uid, device):
    """
    Create a dashboard for a single device based on template
    Returns configured dashboard for the specific device
    """
    dashboard = json.loads(json.dumps(template))  # Deep copy
    
    campus = config['campus']
    building = config['building']
    
    # Replace variable references with actual device name throughout dashboard
    dashboard_str = json.dumps(dashboard)
    dashboard_str = dashboard_str.replace('$RTU_ROB', device)
    dashboard_str = dashboard_str.replace('${RTU_ROB}', device)
    dashboard_str = dashboard_str.replace('PNNL/ROB', f"{campus}/{building}")
    dashboard = json.loads(dashboard_str)
    
    # Update panel titles to remove redundant device name if it's already in title
    if 'panels' in dashboard:
        for panel in dashboard['panels']:
            if 'title' in panel:
                # If title was just the variable, replace with device name
                if panel['title'] == device:
                    continue  # Already set correctly
                # If title contains device name, keep as is
                elif device in panel['title']:
                    continue
                # Otherwise, don't add device name to avoid redundancy in single-device dashboard
    
    # Remove templating variables since we're using fixed device name
    if 'templating' in dashboard:
        dashboard['templating']['list'] = []
    
    # Update dashboard metadata
    timestamp = datetime.now().strftime('%Y-%m-%d %H%M%S')
    dashboard['title'] = f"{campus} {building} - {device} Overview {timestamp}"
    dashboard['id'] = None
    dashboard['uid'] = None
    dashboard['version'] = 0
    
    # Update datasource UID if provided
    if datasource_uid:
        update_datasource_uid(dashboard, datasource_uid)
    
    return dashboard


def generate_rtu_overview(template, config, datasource_uid, grafana_api=None, devices=None):
    """
    Generate RTU Overview dashboard(s) from template.
    
    Returns tuple: (list of dashboards, list of devices)
    - dashboards: List of dashboard dictionaries (one per device if multiple devices found)
    - devices: List of device names that were discovered or provided
    """
    campus = config['campus']
    building = config['building']
    
    # Get devices if not provided and grafana_api is available
    discovered_devices = devices
    if discovered_devices is None and grafana_api is not None:
        logging.info(f"Querying devices from Grafana for {campus}/{building}...")
        discovered_devices = get_variable_values(grafana_api, datasource_uid, campus, building)
        if discovered_devices:
            logging.info(f"Found {len(discovered_devices)} devices: {', '.join(discovered_devices)}")
        else:
            logging.warning("No devices found, using template defaults")
            discovered_devices = None
    
    dashboards = []
    
    # If we have multiple devices, create separate dashboard for each
    if discovered_devices and len(discovered_devices) > 0:
        logging.info(f"Creating separate dashboard for each of {len(discovered_devices)} devices...")
        for device in discovered_devices:
            dashboard = create_dashboard_for_device(template, config, datasource_uid, device)
            dashboards.append({
                'dashboard': dashboard,
                'device': device,
                'filename': f"{campus}_{building}_{device}_RTU_Overview.json"
            })
    else:
        # Single device mode - keep template as is with variables
        dashboard = template.copy()
        new_prefix = f"{campus}/{building}"
        
        # Replace the topic prefix in the entire dashboard
        dashboard = replace_topic_prefix(dashboard, "PNNL/ROB", new_prefix)
        
        # Apply device mapping validation
        dashboard = apply_device_mapping(dashboard, config.get('device_mapping', {}))
        
        # Update dashboard metadata
        timestamp = datetime.now().strftime('%Y-%m-%d %H%M%S')
        dashboard['title'] = f"{campus} {building} - RTU Overview {timestamp}"
        dashboard['id'] = None
        dashboard['uid'] = None
        dashboard['version'] = 0
        
        # Update datasource UID if provided
        if datasource_uid:
            update_datasource_uid(dashboard, datasource_uid)
        
        dashboards.append({
            'dashboard': dashboard,
            'device': None,
            'filename': f"{campus}_{building}_RTU_Overview.json"
        })
    
    return dashboards, discovered_devices


def generate_site_overview(template, config, datasource_uid, grafana_api=None, devices=None):
    """
    Generate Site Overview dashboard from template.
    
    Updates state-timeline panels to include all discovered devices dynamically.
    
    Args:
        template: Dashboard template JSON
        config: Configuration dictionary
        datasource_uid: Grafana PostgreSQL datasource UID
        grafana_api: GrafanaAPI instance (optional, for device discovery)
        devices: List of device names (optional, will query if not provided)
    
    Returns:
        Dashboard dictionary with updated queries for all devices
    """
    # Use deep copy to avoid modifying the template
    dashboard = deepcopy(template)
    
    # Build the topic prefix from config
    campus = config['campus']
    building = config['building']
    new_prefix = f"{campus}/{building}"
    
    # Auto-discover devices from Grafana if not provided
    if devices is None and grafana_api is not None:
        logging.info(f"Querying devices from Grafana for site overview...")
        devices = get_variable_values(grafana_api, datasource_uid, campus, building)
        if devices:
            logging.info(f"Found {len(devices)} devices for site overview: {', '.join(devices)}")
        else:
            logging.warning("No devices found for site overview, using template defaults")
            devices = None
    
    # Update state-timeline panels with dynamic device queries
    if devices and len(devices) > 0:
        logging.info(f"Updating state-timeline panels with {len(devices)} devices...")
        update_statetimeline_panels(dashboard, devices, campus, building)
    
    # Replace the topic prefix in the entire dashboard
    dashboard = replace_topic_prefix(dashboard, "PNNL/ROB", new_prefix)
    
    # Apply device mapping validation
    dashboard = apply_device_mapping(dashboard, config.get('device_mapping', {}))
    
    # Update dashboard metadata
    timestamp = datetime.now().strftime('%Y-%m-%d %H%M%S')
    dashboard['title'] = f"{campus} {building} - Site Overview {timestamp}"
    dashboard['id'] = None
    dashboard['uid'] = None
    dashboard['version'] = 0
    
    # Update datasource UID if provided
    if datasource_uid:
        update_datasource_uid(dashboard, datasource_uid)
    
    return dashboard


def update_statetimeline_panels(dashboard, devices, campus, building):
    """
    Update state-timeline panels to include all discovered devices.
    
    Dynamically builds SQL queries with CASE statements for each device.
    Handles both simple queries and CTE-based queries (e.g., temperature setpoint error).
    
    Args:
        dashboard: Dashboard JSON to update
        devices: List of device names
        campus: Campus name
        building: Building name
    """
    import re
    
    # Panels that should be updated (state-timeline type)
    for panel in dashboard.get('panels', []):
        if panel.get('type') == 'state-timeline' and 'targets' in panel:
            for target in panel['targets']:
                if 'rawSql' in target:
                    query = target['rawSql']
                    
                    # Check if this is a CTE query (contains WITH clause)
                    if 'WITH' in query.upper() and 'zone_temps' in query.lower():
                        # This is the temperature setpoint error query with CTEs
                        update_cte_query(target, devices, campus, building)
                    else:
                        # Simple query - extract metric and rebuild
                        metric_match = re.search(r"'[^']+/([A-Za-z]+)'", query)
                        
                        if metric_match:
                            metric = metric_match.group(1)
                            
                            # Build CASE statements for all devices
                            case_statements = []
                            for device in devices:
                                case_stmt = f"  MAX(CASE WHEN upper(split_part(topic_name, '/', 3)) = '{device.upper()}' THEN cast(value_string as float) END) AS {device}"
                                case_statements.append(case_stmt)
                            
                            cases_sql = ',\n'.join(case_statements)
                            
                            # Build new query
                            new_query = f"""SELECT
  $__timeGroup(ts, $__interval) AS time,
{cases_sql}
FROM data
NATURAL JOIN topics
WHERE topic_name LIKE '{campus}/{building}/%/{metric}'
  AND $__timeFilter(ts)
GROUP BY 1
ORDER BY 1
"""
                            target['rawSql'] = new_query
                            logging.info(f"Updated state-timeline panel with {len(devices)} devices for metric: {metric}")


def update_cte_query(target, devices, campus, building):
    """
    Update CTE-based query (e.g., temperature setpoint error) with discovered devices.
    Uses uppercase device names in column aliases (RTU01, RTU02, etc.) to match expected format.
    
    Args:
        target: Query target to update
        devices: List of device names
        campus: Campus name
        building: Building name
    """
    # Build CASE statements for zone_temps CTE (using uppercase device names in aliases)
    temp_cases = []
    for device in devices:
        device_upper = device.upper()
        temp_case = f"    MAX(CASE WHEN upper(split_part(topic_name, '/', 3)) = '{device_upper}' THEN cast(value_string as float) END) AS {device_upper}_temp"
        temp_cases.append(temp_case)
    
    temp_cases_sql = ',\n'.join(temp_cases)
    
    # Build CASE statements for zone_setpoints CTE (using uppercase device names in aliases)
    sp_cases = []
    for device in devices:
        device_upper = device.upper()
        sp_case = f"    MAX(CASE WHEN upper(split_part(topic_name, '/', 3)) = '{device_upper}' THEN cast(value_string as float) END) AS {device_upper}_sp"
        sp_cases.append(sp_case)
    
    sp_cases_sql = ',\n'.join(sp_cases)
    
    # Build SELECT columns for final query (using uppercase device names)
    select_cols = []
    for device in devices:
        device_upper = device.upper()
        select_col = f"  t.{device_upper}_temp - s.{device_upper}_sp AS {device_upper}"
        select_cols.append(select_col)
    
    select_cols_sql = ',\n'.join(select_cols)
    
    # Build complete CTE query
    new_query = f"""WITH zone_temps AS (
  SELECT
    $__timeGroup(ts, $__interval) AS time,
{temp_cases_sql}
  FROM data
  NATURAL JOIN topics
  WHERE topic_name LIKE '{campus}/{building}/%/ZoneTemperature'
    AND $__timeFilter(ts)
  GROUP BY 1
),
zone_setpoints AS (
  SELECT
    $__timeGroup(ts, $__interval) AS time,
{sp_cases_sql}
  FROM data
  NATURAL JOIN topics
  WHERE topic_name LIKE '{campus}/{building}/%/EffectiveZoneTemperatureSetPoint'
    AND $__timeFilter(ts)
  GROUP BY 1
)
SELECT
  t.time,
{select_cols_sql}
FROM zone_temps t
JOIN zone_setpoints s ON t.time = s.time
ORDER BY t.time
"""
    
    target['rawSql'] = new_query
    logging.info(f"Updated CTE query (temperature setpoint error) with {len(devices)} devices")


def update_datasource_uid(dashboard, datasource_uid):
    """Update all datasource UIDs in dashboard"""
    # Update panel datasources
    for panel in dashboard.get('panels', []):
        if 'datasource' in panel and isinstance(panel['datasource'], dict):
            if panel['datasource'].get('type') == 'postgres':
                panel['datasource']['uid'] = datasource_uid
        
        # Update target datasources
        for target in panel.get('targets', []):
            if 'datasource' in target and isinstance(target['datasource'], dict):
                if target['datasource'].get('type') == 'postgres':
                    target['datasource']['uid'] = datasource_uid
    
    # Update templating datasources
    for template_var in dashboard.get('templating', {}).get('list', []):
        if 'datasource' in template_var and isinstance(template_var['datasource'], dict):
            if template_var['datasource'].get('type') == 'postgres':
                template_var['datasource']['uid'] = datasource_uid


def save_dashboard(dashboard, filename, output_dir='.'):
    """Save dashboard to JSON file"""
    os.makedirs(output_dir, exist_ok=True)
    filepath = os.path.join(output_dir, filename)
    
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(dashboard, f, indent=2)
    
    return filepath


def create_import_wrapper(dashboard, folder_id=0):
    """Create Grafana API import wrapper"""
    return {
        "dashboard": dashboard,
        "folderId": folder_id,
        "overwrite": False
    }


class GrafanaAPI:
    """Grafana API client for dashboard management"""
    
    def __init__(self, url, username, password, verify_ssl=True):
        """
        Initialize Grafana API client with basic authentication
        
        Args:
            url: Grafana base URL (e.g., http://localhost:3000)
            username: Grafana username
            password: Grafana password
            verify_ssl: Whether to verify SSL certificates (default: True)
        """
        self.url = url.rstrip('/')
        self.username = username
        self.password = password
        self.auth = HTTPBasicAuth(username, password)
        self.verify_ssl = verify_ssl
        self.headers = {
            'Content-Type': 'application/json'
        }
        
        if not verify_ssl:
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    def test_connection(self):
        """Test connection to Grafana API"""
        try:
            import requests
            response = requests.get(
                f'{self.url}/api/health',
                auth=self.auth,
                headers=self.headers,
                verify=self.verify_ssl,
                timeout=10
            )
            return response.status_code == 200
        except Exception as e:
            logging.error(f"Connection failed: {e}")
            return False
    
    def get_datasources(self):
        """Get list of datasources"""
        try:
            import requests
            response = requests.get(
                f'{self.url}/api/datasources',
                auth=self.auth,
                headers=self.headers,
                verify=self.verify_ssl,
                timeout=10
            )
            if response.status_code == 200:
                return response.json()
            return []
        except Exception as e:
            logging.error(f"Failed to get datasources: {e}")
            return []
    
    def create_dashboard(self, dashboard, folder_id=0, overwrite=False):
        """
        Create or update dashboard in Grafana
        
        Args:
            dashboard: Dashboard JSON object
            folder_id: Folder ID to create dashboard in (default: 0 = General)
            overwrite: Whether to overwrite existing dashboard
        
        Returns:
            tuple: (success, message, response_data)
        """
        try:
            import requests
            payload = {
                "dashboard": dashboard,
                "folderId": folder_id,
                "overwrite": overwrite,
                "message": f"Created via API at {datetime.now().isoformat()}"
            }
            
            response = requests.post(
                f'{self.url}/api/dashboards/db',
                auth=self.auth,
                headers=self.headers,
                json=payload,
                verify=self.verify_ssl,
                timeout=30
            )
            
            if response.status_code in [200, 201]:
                data = response.json()
                return True, "Dashboard created successfully", data
            else:
                error_msg = response.text
                try:
                    error_json = response.json()
                    error_msg = error_json.get('message', error_msg)
                except:
                    pass
                return False, f"Failed: {error_msg}", None
                
        except Exception as e:
            return False, f"Exception: {str(e)}", None
    
    def get_folders(self):
        """Get list of folders"""
        try:
            import requests
            response = requests.get(
                f'{self.url}/api/folders',
                auth=self.auth,
                headers=self.headers,
                verify=self.verify_ssl,
                timeout=10
            )
            if response.status_code == 200:
                return response.json()
            return []
        except Exception as e:
            logging.error(f"Failed to get folders: {e}")
            return []


def load_grafana_config():
    """Load Grafana API configuration from config.ini"""
    config = configparser.ConfigParser()
    
    try:
        config.read('config.ini')
        if 'grafana' in config:
            url = config.get('grafana', 'url', fallback=None)
            username = config.get('grafana', 'username', fallback=None)
            password = config.get('grafana', 'password', fallback=None)
            verify_ssl = config.getboolean('grafana', 'verify_ssl', fallback=False)
            
            if url and username and password:
                return {
                    'url': url,
                    'username': username,
                    'password': password,
                    'verify_ssl': verify_ssl
                }
            else:
                logging.warning("Incomplete Grafana credentials in config.ini")
                return None
    except Exception as e:
        logging.error(f"Could not read Grafana config: {e}")
        return None
    
    return None


def main():
    """Main execution function"""
    print("=" * 60)
    print("Grafana Dashboard Generator")
    print("=" * 60)
    
    # Load configuration
    print("\n[1/6] Loading configuration from config.ini...")
    config = load_config('config.ini')
    print(f"  Campus: {config['campus']}")
    print(f"  Building: {config['building']}")
    print(f"  Output Directory: {config['output_dir']}")
    
    # Grafana API configuration
    print("\n[2/6] Loading Grafana configuration...")
    grafana_config = load_grafana_config()
    grafana_api = None
    datasource_uid = None
    folder_id = 0
    
    if grafana_config:
        logging.info(f"URL: {grafana_config['url']}")
        logging.info(f"Username: {grafana_config['username']}")
        logging.info(f"SSL Verification: {grafana_config['verify_ssl']}")
        
        print("\n[3/6] Testing Grafana API connection...")
        grafana_api = GrafanaAPI(
            url=grafana_config['url'],
            username=grafana_config['username'],
            password=grafana_config['password'],
            verify_ssl=grafana_config['verify_ssl']
        )
        
        if grafana_api.test_connection():
            logging.info("Connected to Grafana")
            
            # List available datasources and auto-select PostgreSQL
            datasources = grafana_api.get_datasources()
            if datasources:
                postgres_ds = [ds for ds in datasources if ds.get('type') == 'postgres']
                
                if postgres_ds:
                    # Auto-select first PostgreSQL datasource
                    datasource_uid = postgres_ds[0].get('uid')
                    logging.info(f"Auto-selected PostgreSQL datasource: {postgres_ds[0].get('name')}")
                    logging.info(f"UID: {datasource_uid}")
                else:
                    logging.error("No PostgreSQL datasources found in Grafana")
                    logging.error("Please configure a PostgreSQL datasource in Grafana first")
                    print("\nERROR: No PostgreSQL datasource available")
                    print("Please add a PostgreSQL datasource in Grafana and try again")
                    return
            
            # Auto-select General folder (ID: 0)
            folders = grafana_api.get_folders()
            logging.info("Using folder: General (ID: 0)")
        else:
            logging.error("Failed to connect to Grafana API")
            logging.error("Please check your Grafana URL and credentials in config.ini")
            print("\nERROR: Cannot connect to Grafana")
            print("Please verify:")
            print("  1. Grafana URL is correct")
            print("  2. Username and password are valid")
            print("  3. Grafana server is running and accessible")
            return
    else:
        logging.error("No Grafana configuration found in config.ini")
        logging.error("Please add [grafana] section with url, username, and password")
        print("\nERROR: Missing Grafana configuration")
        print("Please add [grafana] section to config.ini with:")
        print("  url = your_grafana_url")
        print("  username = your_username")
        print("  password = your_password")
        return
    
    # Ensure datasource UID was obtained from API
    if not datasource_uid:
        logging.error("Failed to obtain datasource UID from Grafana API")
        print("\nERROR: Could not determine PostgreSQL datasource")
        return
    
    # Load templates
    step_num = 4 if grafana_api else 3
    print(f"\n[{step_num}/6] Loading dashboard templates...")
    try:
        rtu_template = load_template('rtu_overview.json')
        logging.info("Loaded rtu_overview.json")
    except FileNotFoundError:
        logging.error("rtu_overview.json not found")
        return
    
    try:
        site_template = load_template('site_overview.json')
        logging.info("Loaded site_overview.json")
    except FileNotFoundError:
        logging.error("site_overview.json not found")
        return
    
    # Generate dashboards
    step_num += 1
    print(f"\n[{step_num}/6] Generating dashboards...")
    campus = config['campus']
    building = config['building']
    
    # Generate RTU Overview dashboards (one per device if multiple devices found)
    rtu_dashboards, devices = generate_rtu_overview(rtu_template, config, datasource_uid, grafana_api=grafana_api)
    
    # Save each RTU dashboard
    rtu_filepaths = []
    for dash_info in rtu_dashboards:
        dashboard = dash_info['dashboard']
        filename = dash_info['filename']
        device = dash_info['device']
        
        filepath = save_dashboard(dashboard, filename, config['output_dir'])
        rtu_filepaths.append({'filepath': filepath, 'dashboard': dashboard, 'device': device, 'filename': filename})
        
        if device:
            logging.info(f"Generated RTU Overview for {device}: {filepath}")
        else:
            logging.info(f"Generated RTU Overview: {filepath}")
    
    # Generate Site Overview (pass devices for dynamic state-timeline panels)
    site_dashboard = generate_site_overview(site_template, config, datasource_uid, grafana_api, devices)
    site_filename = f"{campus}_{building}_Site_Overview.json"
    site_filepath = save_dashboard(site_dashboard, site_filename, config['output_dir'])
    logging.info(f"Generated Site Overview: {site_filepath}")
    
    # Upload to Grafana via API
    upload_responses = []
    if grafana_api:
        step_num += 1
        print(f"\n[{step_num}/6] Uploading dashboards to Grafana...")
        
        # Upload each RTU Overview dashboard
        for rtu_info in rtu_filepaths:
            dashboard = rtu_info['dashboard']
            device = rtu_info['device']
            
            success, message, data = grafana_api.create_dashboard(dashboard, folder_id)
            
            dashboard_name = f"RTU Overview - {device}" if device else "RTU Overview"
            rtu_response = {
                'dashboard': dashboard_name,
                'device': device,
                'success': success,
                'message': message,
                'data': data,
                'timestamp': datetime.now().isoformat()
            }
            upload_responses.append(rtu_response)
            
            if success:
                dashboard_url = f"{grafana_config['url']}{data.get('url', '')}"
                logging.info(f"{dashboard_name} uploaded")
                logging.info(f"URL: {dashboard_url}")
            else:
                logging.error(f"{dashboard_name} failed: {message}")
        
        # Upload Site Overview
        success, message, data = grafana_api.create_dashboard(site_dashboard, folder_id)
        site_response = {
            'dashboard': 'Site Overview',
            'success': success,
            'message': message,
            'data': data,
            'timestamp': datetime.now().isoformat()
        }
        upload_responses.append(site_response)
        
        if success:
            dashboard_url = f"{grafana_config['url']}{data.get('url', '')}"
            logging.info(f"Site Overview uploaded")
            logging.info(f"URL: {dashboard_url}")
        else:
            logging.error(f"Site Overview failed: {message}")
        
        # Save upload responses to file
        response_output = {
            'upload_time': datetime.now().isoformat(),
            'grafana_url': grafana_config['url'],
            'folder_id': folder_id,
            'devices_count': len(rtu_filepaths),
            'responses': upload_responses
        }
        response_filename = f"{campus}_{building}_upload_response_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        response_filepath = os.path.join(config['output_dir'], response_filename)
        with open(response_filepath, 'w', encoding='utf-8') as f:
            json.dump(response_output, f, indent=2, ensure_ascii=False)
        logging.info(f"Upload responses saved to: {response_filepath}")
    
    # Summary
    step_num += 1
    print(f"\n[{step_num}/6] Summary")
    print("  " + "=" * 56)
    print(f"  Campus/Building: {campus}/{building}")
    print(f"  Topic Prefix: {campus}/{building}")
    print(f"  Datasource UID: {datasource_uid}")
    print(f"  RTU Dashboards: {len(rtu_filepaths)}")
    if grafana_api:
        print(f"  Grafana URL: {grafana_config['url']}")
        print(f"  Target Folder ID: {folder_id if 'folder_id' in locals() else 0}")
    print("  " + "=" * 56)
    print("  Generated Files:")
    for rtu_info in rtu_filepaths:
        device = rtu_info['device']
        filename = rtu_info['filename']
        if device:
            print(f"    • {filename} ({device})")
        else:
            print(f"    • {filename}")
    print(f"    • {site_filename} (Site Overview)")
    print("  " + "=" * 56)
    print("\nDashboard generation complete!")
    
    if grafana_api:
        print("\nDashboards uploaded to Grafana!")
        print(f"View them at: {grafana_config['url']}/dashboards")
    else:
        print("\nUsage:")
        print("  - For Grafana UI: Upload the .json files")
        print("  - For Grafana API: Use the _import.json files")


if __name__ == "__main__":
    main()
