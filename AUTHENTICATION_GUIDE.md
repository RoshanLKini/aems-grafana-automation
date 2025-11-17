# Grafana API Authentication Guide

## Overview

The dashboard generator now uses **Basic Authentication** (username/password) to connect to Grafana at `https://aems1.pnl.gov/grafana`.

## Changes Made

### ✅ Updated Scripts

1. **test_grafana_api.py** - Connection testing with basic auth
2. **generate_dashboards.py** - Dashboard generator with basic auth

### 🔐 Authentication Method

**Old Method:** API Keys (Bearer token)
```python
headers = {'Authorization': f'Bearer {api_key}'}
```

**New Method:** Basic Authentication (username/password)
```python
from requests.auth import HTTPBasicAuth
auth = HTTPBasicAuth(username, password)
requests.get(url, auth=auth)
```

## Usage

### 1. Test Connection

Run the test script to verify your credentials:

```bash
python test_grafana_api.py
```

You will be prompted for:
- **Grafana URL:** (default: https://aems1.pnl.gov/grafana)
- **Username:** Your Grafana username
- **Password:** Your Grafana password (hidden input)
- **SSL Verification:** y/n (default: n)

The script will test:
- ✅ Health endpoint
- ✅ Organization info
- ✅ List datasources (especially PostgreSQL)
- ✅ List folders
- ✅ User information and permissions

### 2. Generate and Upload Dashboards

Run the main generator:

```bash
python generate_dashboards.py
```

**Step-by-step process:**

1. **Load config.ini** - Campus and building settings
2. **Configure datasource** - PostgreSQL UID
3. **Grafana API** - Choose to upload via API (y/n)
   - If yes: Enter username, password
   - Script tests connection
   - Lists available datasources
   - Lists available folders
4. **Generate dashboards** - RTU and Site overview
5. **Upload to Grafana** - Automatic upload via API
6. **Save locally** - Also saves JSON files

## Configuration

### config.ini Example

```ini
campus = PNNL
building = ROB
gateway-address = 
prefix = 
config-subdir = configs
output-dir = .
timezone = America/Los_Angeles
```

### API Configuration (Interactive)

When running `generate_dashboards.py`:

```
Do you want to upload dashboards directly to Grafana? (y/n): y
Enter Grafana URL (default: https://aems1.pnl.gov/grafana): [Enter]
Enter Grafana username: your_username
Enter Grafana password: ********
Verify SSL certificates? (y/n, default: n): n
```

## API Endpoints Used

The scripts interact with these Grafana API endpoints:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/health` | GET | Test connection |
| `/api/org` | GET | Get organization info |
| `/api/user` | GET | Get current user info |
| `/api/datasources` | GET | List datasources |
| `/api/folders` | GET | List folders |
| `/api/dashboards/db` | POST | Create/update dashboard |

## Security Notes

### Password Safety

✅ **Passwords are NOT stored** - They are only used during runtime
✅ **Hidden input** - Password prompt uses `getpass` (hidden typing)
✅ **HTTPS** - Connection to Grafana uses HTTPS
⚠️ **SSL Verification** - Default is disabled for self-signed certificates

### Best Practices

1. **Use strong passwords** for your Grafana account
2. **Don't share credentials** in code or config files
3. **Use environment variables** for automation (optional)
4. **Enable SSL verification** in production

## Troubleshooting

### Connection Refused

**Problem:** `Connection Error: Failed to connect`

**Solutions:**
- Check if URL is correct: `https://aems1.pnl.gov/grafana`
- Ensure you have network access to the server
- Verify Grafana is running

### Authentication Failed

**Problem:** `Status: 401 Unauthorized`

**Solutions:**
- Verify username is correct
- Check password (case-sensitive)
- Ensure account has necessary permissions

### SSL Certificate Error

**Problem:** `SSL Error: certificate verify failed`

**Solutions:**
- Answer 'n' when asked "Verify SSL certificates?"
- Or add the CA certificate to your system

### No PostgreSQL Datasources

**Problem:** `No PostgreSQL datasources found`

**Solutions:**
- Check if datasources are configured in Grafana
- Verify you have permission to view datasources
- Contact Grafana admin

### Dashboard Creation Failed

**Problem:** `Failed: Dashboard name already exists`

**Solutions:**
- The script adds timestamps to avoid conflicts
- Use `overwrite=True` (modify code) to replace existing
- Delete old dashboard first

## Advanced Usage

### Environment Variables (Optional)

You can set environment variables to avoid prompts:

```bash
# Windows
set GRAFANA_URL=https://aems1.pnl.gov/grafana
set GRAFANA_USER=your_username
set GRAFANA_PASS=your_password

# Linux/Mac
export GRAFANA_URL=https://aems1.pnl.gov/grafana
export GRAFANA_USER=your_username
export GRAFANA_PASS=your_password
```

Then modify the script to read from environment variables.

### Batch Processing

Create multiple dashboards with a script:

```python
import os
from generate_dashboards import GrafanaAPI

api = GrafanaAPI(
    url='https://aems1.pnl.gov/grafana',
    username=os.getenv('GRAFANA_USER'),
    password=os.getenv('GRAFANA_PASS'),
    verify_ssl=False
)

# Generate multiple dashboards
for building in ['ROB', 'SIGMA', 'EMSL']:
    # Update config and generate
    ...
```

## Support

### Checking Permissions

Run test script to see your user role:

```bash
python test_grafana_api.py
```

Look for: `✓ Role: Editor` or `✓ Role: Admin`

### Required Permissions

To create dashboards, you need at least **Editor** role.

### Getting Help

1. Check Grafana documentation: https://grafana.com/docs/grafana/latest/
2. Review API reference: https://grafana.com/docs/grafana/latest/http_api/
3. Contact your Grafana administrator

## Files Reference

- `test_grafana_api.py` - Connection testing tool
- `generate_dashboards.py` - Main dashboard generator
- `config.ini` - Campus/building configuration
- `rtu_overview.json` - RTU dashboard template
- `site_overview.json` - Site dashboard template
