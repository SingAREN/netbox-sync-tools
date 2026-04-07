import json
import argparse
import sys
import re
import ipaddress

from parsers.utils import explode_ranges
from logger_setup import get_configured_logger

logger = get_configured_logger('vlan_parser')


def parse_edgecore_vlan(config_text):
    logger.info("Parsing config using EdgeCore logic")
    master_vlan = {"missing": []}
    tmp_vlan = {}

    for line in config_text.split('\n'):
        line = line.strip()

        if not line or line.startswith('!'):
            continue

        # 1. Match VLAN ID
        #  vlan 51 bridge 1 name AS134148_NSCC-A2B_2122 state enable
        m = re.search(r'^vlan\s+(\d+)\s+bridge\s+\d+\s+name\s+(.*)\s+state\s+enable', line)
        if m:
            if tmp_vlan:
                master_vlan.update(tmp_vlan)
            vid = m.group(1)
            name = m.group(2)

            tmp_vlan = {
                vid: {
                    'vid': vid,
                    'vlan_interface': '',
                    'vlan_interface_prefix': {
                        'ipv4': [],
                        'ipv6': []
                    },
                    'vlan_interface_description': '',
                    'vlan_name': name,
                    'interfaces': {
                        'tagged': [],
                        'untagged': []
                    }
                }
            }

    # 2. Append remaining VLAN ID
    master_vlan.update(tmp_vlan)
    master_vlan = vlan_port_mappings(config_text, master_vlan)

    return master_vlan


def parse_slx_vlan(config_text):
    logger.info("Parsing config using SLX logic")
    master_vlan = {"missing": []}
    tmp_vlan = {}

    for line in config_text.split('\n'):
        line = line.strip()

        if not line or line.startswith('!'):
            continue

        # 1. Match VLAN ID
        m = re.search(r'^vlan\s+(\d+)', line)
        if m:
            if tmp_vlan:
                master_vlan.update(tmp_vlan)
            vid = m.group(1)

            tmp_vlan = {
                vid: {
                    'vid': vid,
                    'vlan_interface': '',
                    'vlan_interface_prefix': {
                        'ipv4': [],
                        'ipv6': []
                    },
                    'vlan_interface_description': '',
                    'vlan_name': '',
                    'interfaces': {
                        'tagged': [],
                        'untagged': []
                    }
                }
            }

            continue

        # 2. Match VLAN name
        m = re.search(r'^name\s+(.*)', line)
        if m:
            tmp_vlan[vid]['vlan_name'] = m.group(1)
            continue

        # 3. Match router interface
        m = re.search(r'^router-interface\s+(Ve \d+)', line)
        if m:
            tmp_vlan[vid]['vlan_interface'] = m.group(1)
            continue

    # 4. Append remaining VLAN ID
    master_vlan.update(tmp_vlan)
    master_vlan = vlan_port_mappings(config_text, master_vlan)
    return master_vlan


def vlan_port_mappings(config_text, master_vlan_dict):
    interface = ''

    for line in config_text.split('\n'):
        line = line.strip()

        if not line or line.startswith('!'):
            continue
        # 1. Retrieve interface name
        m = re.search(r'^interface\s+(.*)', line)
        if m:
            interface = m.group(1)

        # 2. Retrieve tagged VLANs from interface
        m = re.search(r'^switchport\s+trunk\s+allowed\s+vlan\s+(add\s+|)(.*)', line)
        if m:
            tagged_vlans = explode_ranges(m.group(2).split(","))
            for vlan in tagged_vlans:
                try:
                    master_vlan_dict[vlan]["interfaces"]["tagged"].append(interface)
                except KeyError:
                    print("Missing VLAN", vlan, "configured on", interface)
                    logger.warning(f"Missing VLAN {vlan} configured on interface {interface}.")
                    master_vlan_dict["missing"].append((interface, vlan))

        # 3. Retrieve untagged VLANs from interface
        m = re.search(r'^switchport\s+access\s+vlan\s+(\d+)', line)
        if m:
            untagged_vlan = m.group(1)
            master_vlan_dict[untagged_vlan]["interfaces"]["untagged"].append(interface)

        # 4. Retrieve interface
        m = re.search(r'^interface\s+(.*)', line)
        if m:
            interface = m.group(1)

        # 5. Retrieve VLAN interface IPv4 prefix
        if "Ve" in interface:
            vid = interface.split()[-1]
            m = re.search(r'^ip\s+address\s+(.*)', line)
            if m:
                address = str(ipaddress.IPv4Interface(m.group(1)))
                master_vlan_dict[vid]['vlan_interface_prefix']['ipv4'].append(address)

        # 6. Retrieve VLAN interface IPv6 prefix
        if "Ve" in interface:
            #   ipv6 address 2001:df0:21a:fff4:0:20:6350:2/64
            m = re.search(r'^ipv6\s+address\s+(.*)', line)
            if m:
                if 'use-link-local-only' in m.group(1):
                    continue
                address = str(ipaddress.IPv6Interface(m.group(1)))
                master_vlan_dict[vid]['vlan_interface_prefix']['ipv6'].append(address)

        # 7. Retrieve VLAN interface description
        if "Ve" in interface:
            #  ip address 103.5.241.18/29
            m = re.search(r'^description\s+(.*)', line)
            if m:
                master_vlan_dict[vid]['vlan_interface_description'] = m.group(1)

    return master_vlan_dict


def main():
    logger.info("--- Started execution of VLAN Parser ---")
    parser = argparse.ArgumentParser(description="Parse SLX-OS VLAN config into JSON.")
    parser.add_argument("input_file", help="Path to the config file")
    parser.add_argument("-t", "--tag", help="Device tag (e.g., device-1)", required=True)
    parser.add_argument("-o", "--output", help="Optional path to save JSON", default=None)

    args = parser.parse_args()

    try:
        with open(args.input_file, 'r') as f:
            config_text = f.read()
            logger.info(f"Successfully read configuration file: {args.input_file}")
    except Exception as e:
        print(f"Error reading file: {e}")
        logger.error(f"Failed to read configuration file '{args.input_file}': {e}")
        sys.exit(1)

    if (args.tag == 'soe-2-ext-100ge') or (args.tag == 'soe-2-ext-oob'):
        parsed_vlan = parse_edgecore_vlan(config_text)
    else:
        parsed_vlan = parse_slx_vlan(config_text)

    final_payload = {"device-tag": args.tag, "vlans": parsed_vlan}
    json_output = json.dumps(final_payload, indent=4)

    if args.output:
        with open(args.output, 'w') as f:
            f.write(json_output)
        print(f"Successfully wrote parsed JSON to {args.output}")
        logger.info(f"Successfully wrote parsed JSON payload to {args.output}")
    else:
        print(json_output)
        logger.info("Successfully parsed config and outputted JSON to console.")

    logger.info("--- Finished execution of VLAN Parser ---")


if __name__ == "__main__":
    main()
