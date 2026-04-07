import os
import json
import glob
from logger_setup import get_configured_logger
from config_loader import get_netbox_config, get_project_root
import pynetbox
import requests

logger = get_configured_logger('interactive_remediation')
PROJECT_ROOT = get_project_root()


def get_netbox_client():
    nb_settings = get_netbox_config()
    nb = pynetbox.api(url=nb_settings['url'], token=nb_settings['token'])
    if nb_settings['disable_tls']:
        session = requests.Session()
        session.verify = False
        import urllib3
        urllib3.disable_warnings()
        nb.http_session = session
    return nb


def gather_vlan_data():
    """Reads all parsed JSON files and fetches NetBox data to build a master map."""
    nb = get_netbox_client()
    json_dir = os.path.join(PROJECT_ROOT, 'data', 'parser_outputs')
    json_files = glob.glob(os.path.join(json_dir, '*.json'))

    if not json_files:
        print(f"No JSON files found in {json_dir}.")
        return None

    # Structure: vlan_master[vid] = {'netbox': 'name', 'netbox_obj': obj, 'devices': {'device-1': 'name'}}
    vlan_master = {}

    # 1. Parse all device JSONs
    for filepath in json_files:
        with open(filepath, 'r') as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                continue

        device_tag = data.get("device-tag", "Unknown-Device")
        vlans = data.get("vlans", {})

        for vid, info in vlans.items():
            if 'missing' in vid:
                continue

            switch_name = info.get("vlan_name", "").strip()
            if not switch_name:
                continue

            if vid not in vlan_master:
                vlan_master[vid] = {'netbox': None, 'netbox_obj': None, 'devices': {}}

            vlan_master[vid]['devices'][device_tag] = switch_name

    # 2. Fetch official NetBox names for these discovered VIDs
    print("Fetching official VLAN names from NetBox...")
    for vid in vlan_master.keys():
        try:
            nb_vlan = nb.ipam.vlans.get(vid=vid)
            if nb_vlan:
                vlan_master[vid]['netbox'] = nb_vlan.name
                vlan_master[vid]['netbox_obj'] = nb_vlan  # Store the actual object for updating later
        except ValueError:
            vlan_master[vid]['netbox'] = "MULTIPLE_ENTRIES_FOUND"
            vlan_master[vid]['netbox_obj'] = None

    return vlan_master


def resolve_conflicts(vlan_master):
    """Identifies conflicts and interactively asks the user to pick the correct name."""
    resolved_names = {}

    for vid, data in vlan_master.items():
        unique_names = set()

        if data['netbox']:
            unique_names.add(data['netbox'])

        for name in data['devices'].values():
            unique_names.add(name)

        # If there's only 1 unique name across the board, it's already in sync
        if len(unique_names) <= 1:
            if unique_names:
                resolved_names[vid] = list(unique_names)[0]
            continue

        # Conflict detected!
        print(f"\n{'-' * 60}")
        print(f" CONFLICT DETECTED: VID {vid}")
        print(f"{'-' * 60}")

        names_list = list(unique_names)

        print("  [0] SKIP (Leave as is for now)")

        for i, name in enumerate(names_list, 1):
            sources = []
            if data['netbox'] == name:
                sources.append("NetBox")
            for dev, d_name in data['devices'].items():
                if d_name == name:
                    sources.append(dev)

            print(f"  [{i}] {name} (Sources: {', '.join(sources)})")

        print(f"  [{len(names_list) + 1}] ENTER CUSTOM NAME")

        choice = -1
        while True:
            try:
                user_input = input(f"\nSelect the correct name for VID {vid} (0-{len(names_list) + 1}): ")
                choice = int(user_input)

                # Option 0: Skip
                if choice == 0:
                    print(f"  [*] Skipping VID {vid}...")
                    break  # Break out of the while loop, leaving it out of resolved_names

                # Option 1 to N: Selected an existing name
                elif 1 <= choice <= len(names_list):
                    resolved_names[vid] = names_list[choice - 1]
                    break

                # Option N+1: Custom Name (with validation)
                elif choice == len(names_list) + 1:
                    while True:
                        custom_name = input("Enter the new correct name (Max 31 chars): ").strip()
                        if len(custom_name) < 32:
                            resolved_names[vid] = custom_name
                            break
                        else:
                            print(f"  [!] Error: Name is {len(custom_name)} characters. Must be less than 32.")
                    break  # Break out of the main selection loop once custom name is validated

                else:
                    print("  [!] Invalid selection. Please pick a number from the menu.")
            except ValueError:
                print("  [!] Please enter a valid number.")

    return resolved_names


def update_netbox_vlans(vlan_master, resolved_names):
    """Updates NetBox with the officially chosen names."""
    print("\n\n" + "=" * 70)
    print(" NETBOX UPDATES")
    print("=" * 70)

    updates_made = False

    for vid, correct_name in resolved_names.items():
        nb_vlan = vlan_master[vid].get('netbox_obj')

        # If the VLAN exists in NetBox but the name doesn't match the chosen correct name
        if nb_vlan and nb_vlan.name != correct_name:
            old_name = nb_vlan.name
            nb_vlan.name = correct_name
            try:
                nb_vlan.save()
                print(f"  [+] NetBox VID {vid}: Updated name from '{old_name}' to '{correct_name}'")
                logger.info(f"Interactive Remediation: Updated NetBox VID {vid} name to '{correct_name}'")
                updates_made = True
            except Exception as e:
                print(f"  [!] Failed to update NetBox VID {vid}: {e}")
                logger.error(f"Interactive Remediation: Failed to update NetBox VID {vid}: {e}")

    if not updates_made:
        print("  [*] NetBox is already aligned with the chosen names.")


def generate_configs(vlan_master, resolved_names):
    """Generates device-specific CLI remediation configs."""
    remediation_tasks = {}

    # Figure out which devices are out of sync with the chosen resolved_name
    for vid, data in vlan_master.items():
        correct_name = resolved_names.get(vid)
        if not correct_name:
            continue  # Skips over any VIDs the user chose to [0] SKIP

        for device_tag, current_name in data['devices'].items():
            if current_name != correct_name:
                if device_tag not in remediation_tasks:
                    remediation_tasks[device_tag] = []
                remediation_tasks[device_tag].append(
                    {'vid': vid, 'correct_name': correct_name, 'old_name': current_name})

    if not remediation_tasks:
        print("\n\n[+] No switch remediation configs needed! All switches match the chosen names.")
        return

    print("\n\n" + "=" * 70)
    print(" SWITCH REMEDIATION CONFIGURATIONS")
    print("=" * 70)

    for device_tag, tasks in remediation_tasks.items():
        print(f"\n[ DEVICE: {device_tag} ]")
        print("!" + "-" * 40)
        print("conf t")

        # Edgecore logic
        if "soe-2-ext" in device_tag.lower():
            for task in tasks:
                print(f"! Changing from '{task['old_name']}'")
                print(f"vlan {task['vid']} bridge 1 name {task['correct_name']} state enable")
                print("commit")

        # SLX-OS / Standard logic
        else:
            for task in tasks:
                print(f"! Changing from '{task['old_name']}'")
                print(f"vlan {task['vid']}")
                print(f" name {task['correct_name']}")

        print("end")
        print("copy run start")
        print("!" + "-" * 40)


def main():
    logger.info("Starting Interactive VLAN Remediation.")
    vlan_master = gather_vlan_data()

    if not vlan_master:
        return

    resolved_names = resolve_conflicts(vlan_master)

    # If the user resolved names (didn't skip everything), proceed with updates
    if resolved_names:
        update_netbox_vlans(vlan_master, resolved_names)
        generate_configs(vlan_master, resolved_names)
    else:
        print("\n[!] No conflicts were resolved. Exiting.")

    logger.info("Finished Interactive VLAN Remediation.")


if __name__ == "__main__":
    main()
