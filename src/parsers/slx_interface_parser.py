import re
import json
import sys
import os
import argparse
from logger_setup import get_configured_logger

logger = get_configured_logger('slx_interface_parser')


# --- Helper Functions ---

def format_mac(mac_str):
    """Converts 'aaaa.bbbb.c315' to 'AA:AA:BB:BB:C3:15' for NetBox."""
    clean_mac = mac_str.replace('.', '').upper()
    if len(clean_mac) == 12:
        return ':'.join(clean_mac[i:i + 2] for i in range(0, 12, 2))
    return mac_str


def get_slx_interface_type(intf_name):
    intf_name_lower = intf_name.lower()
    if intf_name_lower.startswith('loopback') or intf_name_lower.startswith('ve'):
        return 'virtual'
    elif intf_name_lower.startswith('port-channel'):
        return 'lag'
    elif intf_name_lower.startswith('management'):
        return '1000base-t'
    elif intf_name_lower.startswith('ethernet'):
        match = re.search(r'Ethernet\s+\d+/(\d+)', intf_name, re.IGNORECASE)
        if match:
            port_num = int(match.group(1))
            if 1 <= port_num <= 24:
                return '10gbase-x-sfpp'
            elif 25 <= port_num <= 36:
                return '100gbase-x-qsfp28'
    return 'other'


def get_default_mtu(intf_name):
    intf_name_lower = intf_name.lower()
    if intf_name_lower.startswith('ve'):
        return 9194
    elif intf_name_lower.startswith('loopback') or intf_name_lower.startswith('management'):
        return 1500
    else:
        return 9216


# --- Parsers ---

def parse_slx_configs(config_text):
    """Parses SLX running config to extract base interface attributes."""
    interfaces = {}
    blocks = re.finditer(r'^interface\s+(.*?)\n(.*?)(?=^\!|interface)', config_text, re.MULTILINE | re.DOTALL)

    for block in blocks:
        intf_name = block.group(1).strip()
        intf_config = block.group(2)

        intf_data = {
            "name": intf_name,
            "description": "",
            "type": get_slx_interface_type(intf_name),
            "mtu": get_default_mtu(intf_name),
            "vrf": "default",
            "enabled": False,
            "ipv4": [],
            "ipv6": [],
            "mac_address": ""
        }

        desc_match = re.search(r'^\s+description\s+(.*)$', intf_config, re.MULTILINE)
        if desc_match:
            intf_data["description"] = desc_match.group(1).strip()

        if re.search(r'^\s+no shutdown', intf_config, re.MULTILINE):
            intf_data["enabled"] = True

        mtu_match = re.search(r'^\s+mtu\s+(\d+)', intf_config, re.MULTILINE)
        if mtu_match:
            intf_data["mtu"] = int(mtu_match.group(1))

        vrf_match = re.search(r'^\s+vrf forwarding\s+([\w\-]+)', intf_config, re.MULTILINE)
        if vrf_match:
            intf_data["vrf"] = vrf_match.group(1).strip()

        ipv4_matches = re.finditer(r'^\s+ip address\s+([\d\.\/]+)', intf_config, re.MULTILINE)
        for ip in ipv4_matches:
            if 'dhcp' not in ip.group(1):
                intf_data["ipv4"].append(ip.group(1))

        ipv6_matches = re.finditer(r'^\s+ipv6 address\s+([\w\:\/]+)', intf_config, re.MULTILINE)
        for ip in ipv6_matches:
            if 'autoconfig' not in ip.group(1) and 'dhcp' not in ip.group(1):
                intf_data["ipv6"].append(ip.group(1))

        interfaces[intf_name] = intf_data

    return interfaces


def parse_slx_show_interfaces(show_text):
    """Parses the SLX 'show interface' output to extract MAC addresses."""
    mac_mapping = {}
    current_intf = None

    for line in show_text.splitlines():
        line = line.strip()

        # Match interface name header
        intf_match = re.match(r'^([A-Za-z\-]+\s+[\d\/\:]+)\s+is', line)
        if intf_match:
            current_intf = intf_match.group(1).strip()
            continue

        # Extract MAC address and bind to current interface
        if current_intf:
            mac_match = re.search(r'address is ([a-fA-F0-9\.]+)', line)
            # Ensure we only map the first MAC found under a header to avoid missing-header overwrites
            if mac_match and current_intf not in mac_mapping:
                mac_mapping[current_intf] = format_mac(mac_match.group(1))

    return mac_mapping


# --- Main Execution ---

def main():
    parser = argparse.ArgumentParser(description="SLX Interface Parser")
    parser.add_argument("-c", "--config", required=True, help="Path to the running-config file")
    parser.add_argument("-s", "--show", required=True, help="Path to the show interfaces file")
    parser.add_argument("-d", "--device", required=True, help="Device Tag/Name")
    parser.add_argument("-o", "--output", required=True, help="Path to save the JSON output")

    args = parser.parse_args()

    try:
        with open(args.config, 'r') as f:
            config_text = f.read()

        with open(args.show, 'r') as f:
            show_text = f.read()
    except FileNotFoundError as e:
        logger.error(f"File reading error: {e}")
        print(f"Error: {e}")
        sys.exit(1)

    print(f"Parsing configuration for {args.device}...")
    interfaces = parse_slx_configs(config_text)

    print("Parsing show interfaces for MAC addresses...")
    macs = parse_slx_show_interfaces(show_text)

    # Merge MAC addresses into the main interface dictionary
    for intf_name, mac in macs.items():
        if intf_name in interfaces:
            interfaces[intf_name]['mac_address'] = mac
        else:
            # If a MAC exists for an interface not in the config (rare, usually a default port)
            logger.warning(f"Found MAC for {intf_name} but it has no config block. Skipping.")

    # Wrap in our standard payload format
    payload = {
        "device-tag": args.device,
        "interfaces": interfaces
    }

    # Save to JSON
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, 'w') as f:
        json.dump(payload, f, indent=4)

    print(f"[+] Successfully parsed {len(interfaces)} interfaces and saved to {os.path.basename(args.output)}")
    logger.info(f"Successfully parsed interfaces for {args.device}")


if __name__ == "__main__":
    main()
