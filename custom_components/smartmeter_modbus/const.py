"""Constants for the SmartMeter Modbus integration."""

DOMAIN = "smartmeter_modbus"

# Config entry keys
CONF_ADAPTERS = "adapters"
CONF_ADAPTER_NAME = "adapter_name"
CONF_HOST = "host"
CONF_PORT = "port"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_METERS = "meters"
CONF_METER_NAME = "meter_name"
CONF_SLAVE_ID = "slave_id"
CONF_MODEL = "model"
CONF_VENDOR = "vendor"

# Defaults
DEFAULT_PORT = 502
DEFAULT_SCAN_INTERVAL = 30   # seconds
MIN_SCAN_INTERVAL = 5        # seconds
MAX_SCAN_INTERVAL = 3600     # seconds

VENDOR_CHINT = "Chint"
SUPPORTED_VENDORS = [VENDOR_CHINT]

# Diagnostic sensor suffixes (appended to device_unique_id)
DIAG_LAST_UPDATE = "last_update"
DIAG_POLL_OK_COUNT = "poll_ok_count"
DIAG_POLL_FAIL_COUNT = "poll_fail_count"
DIAG_POLL_SUCCESS_RATE = "poll_success_rate"
