import os
import configparser
import sys
from logger_setup import get_configured_logger

logger = get_configured_logger('config_loader')

# Dynamically resolve absolute paths to the configs directory
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, '..'))

NETBOX_CONFIG_FILE = os.path.join(PROJECT_ROOT, 'configs', 'config.ini')
BATCH_CONFIG_FILE = os.path.join(PROJECT_ROOT, 'configs', 'batch_config.ini')


def _read_ini(filepath, preserve_case=False):
    """Internal helper to safely read an INI file."""
    if not os.path.exists(filepath):
        logger.error(f"Configuration file not found: {filepath}")
        print(f"Error: Configuration file '{filepath}' not found.")
        sys.exit(1)

    config = configparser.ConfigParser()
    if preserve_case:
        # Needed for batch_config so device names like 'SOE-2-EXT' don't become lowercase
        config.optionxform = str

    config.read(filepath)
    return config


def get_netbox_config():
    """Reads config.ini and returns a dictionary of NetBox settings."""
    config = _read_ini(NETBOX_CONFIG_FILE)
    try:
        return {
            "url": config.get("NetBox", "URL").strip('"\''),
            "token": config.get("NetBox", "TOKEN").strip('"\''),
            "disable_tls": config.getboolean("NetBox", "DISABLE_TLS_WARNINGS", fallback=False)
        }
    except configparser.NoOptionError as e:
        logger.error(f"Missing required NetBox configuration parameter: {e}")
        sys.exit(1)


def get_batch_config():
    """Reads batch_config.ini and returns the ConfigParser object to iterate over."""
    return _read_ini(BATCH_CONFIG_FILE, preserve_case=True)


# We also expose PROJECT_ROOT here so other files (like batch_runner)
# don't have to keep calculating it!
def get_project_root():
    return PROJECT_ROOT
