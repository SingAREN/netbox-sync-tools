# NetBox VLAN Synchronization Pipeline

## Overview
This automated pipeline extracts VLAN and interface mappings from network device configurations (SLX-OS and Edgecore) and synchronizes them into NetBox. The toolset consists of a configuration parser, a NetBox importer, and a batch runner to process multiple devices sequentially.

## Architecture
The solution relies on three core Python scripts:
1. **`batch_parser.py`**: The orchestrator. It reads a batch configuration file and executes the parser and importer for each defined device using subprocesses.
2. **`vlan_parser_v1.2.py`**: Reads raw switch configuration text files, identifies VLANs, tagged/untagged port mappings, and IP prefixes, and exports this data into a standardized JSON payload.
3. **`netbox_vlan_importer.py`**: Consumes the JSON payload and pushes the state to NetBox. It handles creating/updating VLANs, applying device tags, and synchronizing the 802.1Q modes (tagged/access) on specific NetBox interfaces.

## Prerequisites & Assumptions

Before running the pipeline, ensure the following requirements are met:

* **Python Packages:** The following dependencies must be installed in your environment:
  ```bash
  pip install pynetbox requests
  ```
* **NetBox Pre-population:** The script operates under the assumption that the **Device** and its corresponding **Interfaces** (e.g., Ethernet 0/1, Ve 10) *already exist* within NetBox. The importer's job is to synchronize VLAN tags and 802.1Q modes to existing infrastructure; it does not automatically provision missing devices or physical/logical port objects.
* **Device Naming:** The `DEVICE` variable in your `batch_config.ini` must exactly match the device name as it is configured in NetBox.


## Configuration Files

The pipeline requires two initialization files to operate. 

### 1. `config.ini` (NetBox Credentials)
This file is required by `netbox_vlan_importer.py` to authenticate with your NetBox instance. It must be placed in the same directory as the script.
```ini
[NetBox]
URL = "http://YOUR_NETBOX_URL"
TOKEN = "YOUR_API_TOKEN"
DISABLE_TLS_WARNINGS = True
```

### 2. `batch_config.ini` (Batch Execution Definitions)
This file is used by `batch_parser.py` to define the queue of devices to process. Each device should have its own section. Keys are case-sensitive.
```ini
[Device_1_SiteA]
CONFIGURATION_FILEPATH = "/path/to/raw/switch_config_1.txt"
TAG = "device-1"
OUTPUT_FILEPATH = "/path/to/parsed_payload_1.json"
DEVICE = "netbox-device-name-1"

[Device_2_SiteB]
CONFIGURATION_FILEPATH = "/path/to/raw/switch_config_2.txt"
TAG = "soe-2-ext-100ge"
OUTPUT_FILEPATH = "/path/to/parsed_payload_2.json"
DEVICE = "netbox-device-name-2"
```
*Note: The parser automatically applies Edgecore parsing logic if the `TAG` is `soe-2-ext-100ge` or `soe-2-ext-oob`. Otherwise, it defaults to SLX-OS logic.*

## Usage

To run the pipeline across all devices defined in your configuration file, simply execute the batch runner:

```bash
python batch_parser.py
```

### Running Scripts Individually
You can also bypass the batch runner and execute the scripts manually for testing or single-device runs:

**1. Parse Configuration:**
```bash
python vlan_parser_v1.2.py <path_to_config.txt> -t <device_tag> -o <output_file.json>
```

**2. Import to NetBox:**
```bash
python netbox_vlan_importer.py <path_to_parsed.json> -d <netbox_device_name>
```

## Audit Logging
Both the parser and the importer automatically append execution details, errors, and state changes (such as added/removed VLAN tags on interfaces) to a centralized log file named `vlan_sync_audit.log` located in the execution directory.



## Project Structure

```text
netbox-sync-tools/
├── configs/                     # All configuration files
│   ├── config.ini               # NetBox credentials
│   └── batch_config.ini         # Batch execution definitions
├── data/                        # File inputs and outputs (Usually added to .gitignore)
│   ├── network_configs/         # Raw text configuration files from switches
│   └── parser_outputs/          # The intermediate JSON files
├── logs/                        # Centralized log directory
│   └── sync_audit.log           # All scripts append here
├── src/                         # Your actual Python source code
│   ├── __init__.py
│   ├── batch_runner.py          # The main entry point (formerly batch_parser.py)
│   ├── parsers/                 # Modules dedicated to reading switch text
│   │   ├── __init__.py
│   │   ├── utils.py             # Shared parsing tools (e.g., explode_ranges)
│   │   ├── vlan_parser.py       
│   │   ├── device_parser.py     
│   │   └── prefix_parser.py     
│   └── importers/               # Modules dedicated to updating NetBox
│       ├── __init__.py
│       ├── netbox_client.py     # Centralized NetBox Auth and shared API tools (tags)
│       ├── vlan_importer.py     
│       ├── device_importer.py   
│       └── prefix_importer.py   
├── tests/                       # Your unit tests
│   ├── test_vlan_parser.py
│   └── test_netbox_importer.py
├── .gitignore                   # To prevent committing credentials/network configs
├── requirements.txt             # pip install -r requirements.txt
└── README.md                    # Your documentation
```