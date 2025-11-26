# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

LitterRobotControl is a Flask-based web service that interfaces with Litter-Robot devices via the pylitterbot library and provides HTTP endpoints for monitoring and controlling litter box cleaning cycles. The project also includes TP-Link Kasa smart plug control and data analysis tools for optimizing cleaning schedules.

## Environment Setup

### Python Virtual Environment

This project uses a Python virtual environment. Two venv directories exist (`venv/` and `wsl-venv/`):
- `venv/` - Windows Python environment
- `wsl-venv/` - WSL Python environment

To activate the appropriate environment:
```bash
# Windows
venv\Scripts\activate

# WSL
source wsl-venv/bin/activate
```

### Dependencies

Install dependencies using:
```bash
pip install -r requirements.txt
```

### Environment Variables

Create a `.env` file in the project root with the following credentials:
```
# Litter-Robot (Whisker) API credentials
WHISKER_USERNAME=<your_litter_robot_account_email>
WHISKER_PASSWORD=<your_litter_robot_account_password>

# TP-Link Kasa smart plug credentials (required for smart_plug_control.py and litter_robot_recovery.py)
KASA_USERNAME=<your_kasa_account_email>
KASA_PASSWORD=<your_kasa_account_password>
SMART_PLUG_IP=192.168.0.80

# Optional daemon configuration (defaults shown)
CHECK_INTERVAL_SECONDS=10           # Polling frequency (default: 10s)
HEARTBEAT_INTERVAL_MINUTES=5        # Heartbeat log frequency (default: 5 min)
ERROR_TIMEOUT_MINUTES=30            # Wait before recovery (default: 30 min)
POWER_CYCLE_WAIT_SECONDS=7          # Power cycle duration (default: 7s)
MAX_RECOVERY_ATTEMPTS=3             # Max recovery tries (default: 3)

# Feature flags (optional)
ENABLE_RECOVERY=true                # Enable error recovery (default: true)
ENABLE_SCHEDULED_CLEANING=true      # Enable scheduled cleaning (default: true)

# Scheduled cleaning configuration (optional)
CLEANING_TIMES=02:29,11:29,16:29,23:29  # Comma-separated HH:MM times
TIMEZONE=US/Mountain                # pytz timezone string

# Webhook notifications (optional)
WEBHOOK_URL=https://ntfy.sh/...     # For Discord, Slack, ntfy, etc.
```

**IMPORTANT**: The `.env` file contains sensitive credentials and should never be committed to version control.

## Running the Application

### Flask Web Service

Run the Flask application locally:
```bash
python app.py
```

The application provides these HTTP endpoints:
- `GET /liveness` - Health check showing uptime
- `GET /info` - Returns robot information and insights
- `POST /trigger_cleaning` - Triggers a cleaning cycle

### WSGI Deployment

The `wsgi.py` file is configured for PythonAnywhere deployment at `iamdaviddunlap.pythonanywhere.com`.

### Standalone Scripts

Run the sync version directly:
```bash
# Full test (info + insight + cleaning)
python litter_robot_sync.py FULL_TEST

# Partial test (info + insight only, no cleaning)
python litter_robot_sync.py PARTIAL_TEST

# Cleaning only
python litter_robot_sync.py CLEANING
```

Run the unified daemon (monitoring, recovery, and scheduled cleaning):
```bash
python litter_robot_daemon.py
```

Test the daemon with a single check:
```bash
python test_daemon.py
```

Run data analysis:
```bash
python process_data.py
```

Run smart plug control:
```bash
python smart_plug_control.py
```

### Legacy Scripts

The following legacy scripts are deprecated but kept for reference:
- `away_automation.py` - Old scheduled cleaning (use `litter_robot_daemon.py` instead)
- `away_automation_v2.py` - Old combined daemon (replaced by `litter_robot_daemon.py`)
- `recovery_daemon.py` - Old recovery-only daemon (merged into `litter_robot_daemon.py`)

## Architecture

### Async vs Sync Implementations

The codebase maintains two parallel implementations for Litter-Robot control:

1. **Async version** (`litter_robot_async.py`):
   - Native async/await implementation
   - Used by Flask routes via `loop.run_until_complete()`
   - Functions: `get_account()`, `get_insight()`, `trigger_cleaning()`, `get_info()`

2. **Sync version** (`litter_robot_sync.py`):
   - Wraps async operations in `safe_sync_run()` helper
   - Used for standalone scripts and scheduled automation
   - Same function signatures as async version

Both implementations use the `pylitterbot` library to communicate with Litter-Robot's Whisker API.

### Flask Integration Pattern

The Flask app (`app.py`) uses a global event loop to bridge async operations:
```python
loop = asyncio.get_event_loop()

@app.route('/info')
def report_info():
    info = loop.run_until_complete(get_info())
    return info
```

This pattern allows Flask to work with the async pylitterbot API without requiring Flask async support.

### Account Connection Pattern

All Litter-Robot operations follow this pattern:
1. Load credentials from `.env`
2. Create and connect `Account` object
3. Perform operation on `account.robots[0]`
4. Always disconnect in a `finally` block

### Data Analysis Tools

`process_data.py` provides utilities for analyzing litter box usage patterns:
- `get_litter_box_trigger_datetime_list()` - Fetches complete activity history
- `generate_histogram()` - Visualizes usage patterns throughout the day
- `find_best_times()` - Calculates optimal cleaning schedule times based on historical data

### Smart Plug Integration

`smart_plug_control.py` controls TP-Link Kasa smart plugs using credentials from the `.env` file.

### Unified Daemon Architecture

The project uses a modular daemon architecture in the `litterbot/` package:

```
litterbot/
├── config.py              # Configuration management
├── state.py               # State persistence with change detection
├── robot_client.py        # Whisker API connection
├── smart_plug.py          # Kasa smart plug control
├── notifier.py            # Notification system (webhooks, logs)
├── classifier.py          # Status classification (NONE/WAIT/POWER_CYCLE/NOTIFY_USER)
├── recovery.py            # Recovery strategies
├── scheduler.py           # Scheduled cleaning logic
├── monitor.py             # Status monitoring with change detection
└── daemon.py              # Main orchestrator
```

**Main Entry Point:** `litter_robot_daemon.py`

**Key Features:**
- **Unified Daemon**: Combines error monitoring, recovery, and scheduled cleaning
- **Fast Polling**: Checks status every 10 seconds (configurable)
- **Smart Logging**:
  - Logs status changes immediately when detected
  - Periodic heartbeat logs (every 5 min) to confirm daemon is alive
  - No log spam during normal operation
- **Error Classification**: 4 categories (Normal, Transient, Power-Cycleable, User-Intervention)
- **State Persistence**: Survives daemon restarts (`daemon_state.json`)
- **Webhook Notifications**: Discord, Slack, ntfy, etc.
- **Feature Flags**: Enable/disable recovery or scheduling independently
- **Configurable Schedule**: Cleaning times and timezone via .env

**Usage:**
```bash
python litter_robot_daemon.py
```

**Testing:**
```bash
python test_daemon.py  # Single check, then exit
```

**Configuration (.env):**
```bash
CHECK_INTERVAL_SECONDS=10           # Polling frequency (default: 10s)
HEARTBEAT_INTERVAL_MINUTES=5        # Heartbeat log frequency (default: 5 min)
ERROR_TIMEOUT_MINUTES=30            # Wait before recovery (default: 30 min)
ENABLE_RECOVERY=true                # Enable error recovery
ENABLE_SCHEDULED_CLEANING=true      # Enable scheduled cleaning
CLEANING_TIMES=02:29,11:29,16:29,23:29
TIMEZONE=US/Mountain
WEBHOOK_URL=https://ntfy.sh/...     # Optional notifications
```

**Logging Output:**

Normal operation (quiet):
```
2025-11-26 10:00:00 | INFO | Litter Robot Daemon Starting
2025-11-26 10:05:00 | INFO | Heartbeat: Robot status is READY
2025-11-26 10:10:00 | INFO | Heartbeat: Robot status is READY
```

When changes occur:
```
2025-11-26 10:12:30 | INFO | Status changed: READY → CAT_DETECTED
2025-11-26 10:13:00 | INFO | Status changed: CAT_DETECTED → READY
```

**Error Categories:**
- **Normal**: `READY`, `CLEAN_CYCLE_COMPLETE`, `OFF` → No action
- **Transient**: `CLEAN_CYCLE`, `CAT_DETECTED`, `PAUSED` → Wait and see
- **Power-Cycleable**: Over torque, position faults, sensor faults → Auto-recovery
- **User Intervention**: Drawer full, bonnet removed, offline → Notify only

## Key Dependencies

- `pylitterbot` - Litter-Robot API client
- `flask` - Web framework
- `python-dotenv` - Environment variable management (≥1.2.0 for proper handling of special characters)
- `apscheduler` / `schedule` - Task scheduling (legacy daemon only)
- `matplotlib` / `pandas` - Data visualization and analysis
- `python-kasa` - TP-Link smart plug control
- `aiohttp` - Async HTTP client (for webhook notifications)

## Important Notes

- **Sensitive Data**: All credentials are stored in `.env` file (never commit to version control)
  - **Special Characters in .env**: Passwords with `$` characters must use `dotenv_values()` instead of `load_dotenv()` to avoid shell variable expansion
  - All code now uses `dotenv_values()` for proper handling of special characters
- **Performance**: Flask routes take 2-3 seconds per API call (noted in git history)
- **Timezone**: Daemon uses configurable timezone (default: US Mountain Time / `America/Denver`)
- **Default Robot**: Code assumes account has at least one robot and always uses `robots[0]`
- **Unified Daemon**: `litter_robot_daemon.py` replaces both `recovery_daemon.py` and `away_automation_v2.py`
  - Modular architecture in `litterbot/` package
  - 10-second polling by default (was 60s)
  - Smart change-detection logging (no spam)
  - Configurable via .env file
- **WSL vs Windows**: Two separate virtual environments exist for cross-platform development; use the appropriate one for your system
  - `wsl-venv/` for WSL/Linux
  - `venv/` for Windows
