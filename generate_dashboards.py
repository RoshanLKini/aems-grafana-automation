"""
Grafana Dashboard Generator

This script automates the generation of Grafana dashboards for building automation systems.
It queries devices from a PostgreSQL datasource, creates separate dashboards for each device,
and uploads them to Grafana via API.

Features:
- Auto-discovers devices from Grafana PostgreSQL datasource
- Creates separate dashboard for each RTU device
- Generates site overview dashboard
- Supports basic authentication for Grafana API
- Validates device point mappings
- Saves all output to configurable directory

Usage:
    python generate_dashboards.py

Configuration:
    Edit config.ini to set campus, building, Grafana credentials, and device mappings
"""

import json
import configparser
from datetime import datetime
import os
import requests
import urllib3
import getpass
import logging
from requests.auth import HTTPBasicAuth

# Configure logging to display informational messages
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s: %(message)s'
)


def get_variable_values(grafana_api, datasource_uid, campus, building):
    """
    Query Grafana PostgreSQL datasource to discover all devices for a campus/building.
    
    This function queries the topics table to find all devices that have ZoneTemperature
    data points, which indicates they are active RTU devices.
    
    Args:
        grafana_api: GrafanaAPI instance with connection details
        datasource_uid: UID of the PostgreSQL datasource in Grafana
        campus: Campus name (e.g., 'PNNL')
        building: Building name (e.g., 'ROB')
    
    Returns:
        List of device names (e.g., ['rtu01', 'rtu02', 'rtu03', 'rtu04'])
        Empty list if query fails or no devices found
    """
    try:
        # Query to get all RTU devices based on ZoneTemperature topic
        query = f"select topic_name from topics where topic_name like '{campus}/{building}/%/ZoneTemperature'"
        
        # Use Grafana datasource query API to execute the SQL query
        payload = {
            "queries": [{
                "datasource": {"type": "postgres", "uid": datasource_uid},
                "rawSql": query,
                "format": "table"
            }]
        }
        
        # Execute the query via Grafana API
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
            
            # Parse the response to extract device names from topic paths
            if 'results' in data:
                for result_key in data['results']:
                    result = data['results'][result_key]
                    if 'frames' in result:
                        for frame in result['frames']:
                            if 'data' in frame and 'values' in frame['data']:
                                for values in frame['data']['values']:
                                    for topic_name in values:
                                        # Topic format: campus/building/device/point
                                        # Extract device name (index 2)
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
    """
    Load configuration from INI file.
    
    Reads campus/building information, output directory, timezone, and device mappings
    from the config.ini file.
    
    Args:
        config_file: Path to configuration file (default: 'config.ini')
    
    Returns:
        Dictionary containing configuration values including:
        - campus: Campus name
        - building: Building name
        - output_dir: Directory for generated files
        - timezone: Timezone for dashboards
        - device_mapping: Dictionary of device point mappings
    """
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
    
    # Load device point mapping from config
    # Maps generic point names to actual device point names
    if config.has_section('device_mapping'):
        result['device_mapping'] = dict(config.items('device_mapping'))
        logging.info(f"Loaded {len(result['device_mapping'])} device mappings from config")
    else:
        result['device_mapping'] = {}
        logging.warning("No device_mapping section found in config.ini")
    
    return result


def load_template(template_file):
    """
    Load dashboard template from JSON file.
    
    Args:
        template_file: Path to JSON template file
    
    Returns:
        Dictionary containing dashboard template
    """
    with open(template_file, 'r', encoding='utf-8') as f:
        return json.load(f)


def replace_topic_prefix(content, old_prefix, new_prefix):
    """
    Replace topic name prefix throughout the dashboard JSON.
    
    Updates all references from template prefix (e.g., 'PNNL/ROB')
    to the configured campus/building prefix.
    
    Args:
        content: Dashboard JSON content
        old_prefix: Old topic prefix to replace
        new_prefix: New topic prefix
    
    Returns:
        Updated dashboard content
    """
    content_str = json.dumps(content)
    content_str = content_str.replace(old_prefix, new_prefix)
    return json.loads(content_str)


def apply_device_mapping(content, device_mapping):
    """
    Validate device point mappings against dashboard content.
    
    Checks that device points used in the dashboard are defined in the
    device_mapping section of config.ini. Logs warnings for unmapped points
    and info for unused mappings.
    
    Args:
        content: Dashboard JSON content
        device_mapping: Dictionary of device point mappings from config
    
    Returns:
        Unchanged dashboard content (validation only)
    """
    if not device_mapping:
        logging.warning("No device mapping provided, skipping validation")
        return content
    
    content_str = json.dumps(content)
    
    # Extract all point names used in the dashboard using regex
    import re
    used_points = set(re.findall(r'/([A-Za-z0-9_]+)(?:\'|\s)', content_str))
    
    # Get mapped point names (values from config)
    mapped_points = set(device_mapping.values())
    
    # Find points used in dashboard but not in mapping
    # Exclude known system points that aren't device-specific
    unmapped_points = used_points - mapped_points - {
        'topics', 'data', 'meter', 'air_temperature', 'Watts'
    }
    
    if unmapped_points:
        logging.warning(f"Points in dashboard not in device_mapping: {sorted(unmapped_points)}")
    
    # Find mapped points not used in dashboard (informational)
    unused_mappings = mapped_points - used_points
    if unused_mappings:
        logging.info(f"Mapped points not used in this dashboard: {sorted(unused_mappings)}")
    
    return content


def create_dashboard_for_device(template, config, datasource_uid, device):
    """
    Create a customized dashboard for a single RTU device.
    
    Takes the template dashboard and replaces all variable references with
    the specific device name, creating a dedicated dashboard for that device.
    
    Args:
        template: Dashboard template JSON
        config: Configuration dictionary
        datasource_uid: Grafana datasource UID
        device: Device name (e.g., 'rtu01')
    
    Returns:
        Dictionary containing configured dashboard for the device
    """
    # Create deep copy to avoid modifying template
    dashboard = json.loads(json.dumps(template))
    
    campus = config['campus']
    building = config['building']
    
    # Replace all variable references with actual device name
    # This converts dashboard from using $RTU_ROB variable to fixed device name
    dashboard_str = json.dumps(dashboard)
    dashboard_str = dashboard_str.replace('$RTU_ROB', device)
    dashboard_str = dashboard_str.replace('${RTU_ROB}', device)
    dashboard_str = dashboard_str.replace('PNNL/ROB', f"{campus}/{building}")
    dashboard = json.loads(dashboard_str)
    
    # Clean up panel titles to avoid redundancy
    # In a single-device dashboard, we don't need device name in every panel title
    if 'panels' in dashboard:
        for panel in dashboard['panels']:
            if 'title' in panel:
                # Panel titles are already updated via string replacement above
                # No additional modification needed
                pass
    
    # Remove templating variables since we're using a fixed device name
    # Variables are not needed when dashboard is device-specific
    if 'templating' in dashboard:
        dashboard['templating']['list'] = []
    
    # Update dashboard metadata with device-specific information
    timestamp = datetime.now().strftime('%Y-%m-%d %H%M%S')
    dashboard['title'] = f"{campus} {building} - {device} Overview {timestamp}"
    dashboard['id'] = None  # Let Grafana assign new ID
    dashboard['uid'] = None  # Let Grafana assign new UID
    dashboard['version'] = 0  # Start at version 0
    
    # Update datasource UID to point to correct PostgreSQL datasource
    if datasource_uid:
        update_datasource_uid(dashboard, datasource_uid)
    
    return dashboard


def generate_rtu_overview(template, config, datasource_uid, grafana_api=None, devices=None):
    """
    Generate RTU Overview dashboards from template.
    
    This function auto-discovers devices from Grafana and creates a separate
    dashboard for each device found. If no devices are found, creates a single
    dashboard with variable selector.
    
    Args:
        template: Dashboard template JSON
        config: Configuration dictionary
        datasource_uid: Grafana PostgreSQL datasource UID
        grafana_api: GrafanaAPI instance (optional, for device discovery)
        devices: List of device names (optional, will query if not provided)
    
    Returns:
        List of dictionaries, each containing:
        - dashboard: Dashboard JSON
        - device: Device name (or None for variable-based dashboard)
        - filename: Suggested filename for the dashboard
    """
    campus = config['campus']
    building = config['building']
    
    # Auto-discover devices from Grafana if not provided
    if devices is None and grafana_api is not None:
        logging.info(f"Querying devices from Grafana for {campus}/{building}...")
        devices = get_variable_values(grafana_api, datasource_uid, campus, building)
        if devices:
            logging.info(f"Found {len(devices)} devices: {', '.join(devices)}")
        else:
            logging.warning("No devices found, using template defaults")
            devices = None
    
    dashboards = []
    
    # Create separate dashboard for each device
    if devices and len(devices) > 0:
        logging.info(f"Creating separate dashboard for each of {len(devices)} devices...")
        for device in devices:
            dashboard = create_dashboard_for_device(template, config, datasource_uid, device)
            dashboards.append({
                'dashboard': dashboard,
                'device': device,
                'filename': f"{campus}_{building}_{device}_RTU_Overview.json"
            })
    else:
        # Fallback: Single dashboard with variable selector
        # Used when device auto-discovery fails or returns no results
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
    
    return dashboards


def generate_site_overview(template, config, datasource_uid):
    """Generate Site Overview dashboard from template"""
    dashboard = template.copy()
    
    # Build the topic prefix from config
    campus = config['campus']
    building = config['building']
    new_prefix = f"{campus}/{building}"
    
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
    rtu_dashboards = generate_rtu_overview(rtu_template, config, datasource_uid, grafana_api=grafana_api)
    
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
    
    # Generate Site Overview
    site_dashboard = generate_site_overview(site_template, config, datasource_uid)
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
