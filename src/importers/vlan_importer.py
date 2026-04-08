import json
import argparse
import sys

# Import the shared client and tools from our local module
from netbox_client import get_netbox_client, get_or_create_tag
from logger_setup import get_configured_logger

logger = get_configured_logger('vlan_importer')


def port_based_vlan_mapping(vlans):
    all_interfaces = set()

    # 1. Scan interfaces from output.json and store within all_interfaces set to ensure unique interfaces
    for vid, vlan_info in vlans.items():
        if 'missing' in vid:
            continue
        interfaces = vlan_info["interfaces"]["tagged"] + vlan_info["interfaces"]["untagged"]
        for interface in interfaces:
            all_interfaces.add(interface)

    # 2. Instantiate interface dictionary in preparation for assigning VLAN IDs to interfaces
    interface_dict = {i: {'tagged': [], 'untagged': ''} for i in all_interfaces}

    # 3. Add tagged and untagged VLAN assignments to interface
    for vid, vlan_info in vlans.items():
        if 'missing' in vid:
            continue
        for interface in vlan_info["interfaces"]["tagged"]:
            interface_dict[interface]['tagged'].append(vid)
        for interface in vlan_info["interfaces"]["untagged"]:
            interface_dict[interface]['untagged'] = vid

    return interface_dict


def add_update_vlan_list_to_netbox(nb, vlans, tag_obj):
    current_vlan_list = []

    for vid, info in vlans.items():
        if 'missing' in vid:
            for i in info:
                print('Skip missing VLANs', " ".join(i))
            continue

        name = info.get("vlan_name") or 'UNASSIGNED_SYSTEM_VLAN'
        status = 'active'

        print(f"\n--- Processing VLAN: {vid} (Name: {name}) ---")

        try:
            vlan = nb.ipam.vlans.get(vid=vid)
        except ValueError:
            print(f'  [~] Multiple VLAN entries found for VID: {vid}. Trying to find specific VLAN with {name}')
            vlan = nb.ipam.vlans.get(vid=vid, name=name)

        if vlan:
            print(f"  [~] VLAN ID: {vid} already exists. Checking for changes...")
            needs_update = False
            audit_changes = []

            # 1. Compare Name (Modified: NetBox is the Source of Truth)
            if vlan.name != name:
                # We record the mismatch but DO NOT change vlan.name or trigger a save.
                warning_msg = f"Name Mismatch: Switch config says '{name}', but NetBox says '{vlan.name}'"
                print(f"      - [!] {warning_msg}. NetBox name retained.")
                logger.warning(f"VLAN VID {vid} {warning_msg}")

            # 2. Compare Status
            # pynetbox choice fields return objects. Safely get the string value to compare.
            current_status = getattr(vlan.status, 'value', str(vlan.status))
            if current_status != status:
                audit_changes.append(f"Status changed from '{current_status}' to '{status}'")
                vlan.status = status
                needs_update = True
                print(f"      - Status changed to: {status}")

            # 3. Compare Description
            # if vlan.description != description:
            #     vlan.description = description
            #     needs_update = True
            #     print(f"      - Description changed to: {description}")

            # 4. Compare Tags
            # Extract existing tag IDs from the pynetbox nested objects
            existing_tag_ids = [t.id for t in getattr(vlan, 'tags', [])]
            if tag_obj.id not in existing_tag_ids:
                existing_tag_ids.append(tag_obj.id)
                vlan.tags = [{'id': tid} for tid in existing_tag_ids]  # pynetbox expects list of dicts/IDs
                audit_changes.append(f"Tag added: {tag_obj.name}")
                needs_update = True
                print(f"      - Tag added: {tag_obj.name}")

            # 5. Save only if changes were detected
            if needs_update:
                try:
                    vlan.save()
                    print("  [+] Update successful.")
                    logger.info(f"Updated VLAN VID {vid} (ID: {vlan.id}) - Changes: " + " | ".join(audit_changes))
                except Exception as e:
                    print(f"  [!] Update failed: {e}")
                    logger.error(f"Failed to update VLAN VID {vid}: {e}")
            else:
                print("  [-] No changes detected. Skipping update.")

            current_vlan_list.append(vlan)

        else:
            print(f"  [*] Creating new VLAN ID: {vid}...")
            description = info.get('vlan_interface_description') or "Auto-import from netbox_vlan_importer"
            try:
                vlan = nb.ipam.vlans.create(
                    vid=vid,
                    name=name,
                    status=status,
                    description=description,
                    tags=[{'id': tag_obj.id}]
                )
                current_vlan_list.append(vlan)
                print(f"  [+] VLAN created successfully! (ID: {vlan.id})")
                logger.info(f"Created new VLAN VID {vid} (ID: {vlan.id}) with Name '{name}'")
            except Exception as e:
                print(f"  [!] Creation failed: {e}")
                logger.error(f"Failed to create VLAN VID {vid}: {e}")

    return current_vlan_list


def sync_vlan_port_mappings(interface_list, port_mappings, vlan_list):
    # Step 1: Create the lookup dictionary (VID string -> NetBox ID)
    vlan_lookup = {str(vlan.vid): vlan.id for vlan in vlan_list}

    for interface in interface_list:

        # Step 2: Determine Desired State
        if interface.name in port_mappings:
            mapping = port_mappings[interface.name]
            desired_untagged_vid = mapping.get('untagged', '')
            desired_untagged_id = vlan_lookup.get(desired_untagged_vid) if desired_untagged_vid else None

            desired_tagged_vids = mapping.get('tagged', [])
            desired_tagged_ids = [vlan_lookup[vid] for vid in desired_tagged_vids if vid in vlan_lookup]
        else:
            # If interface is not in the mapping, the desired state is completely empty
            desired_untagged_id = None
            desired_tagged_ids = []

        # Step 3: Determine Current State (from PyNetbox)
        # Safely extract existing IDs
        current_untagged_id = getattr(interface.untagged_vlan, 'id', None) if getattr(interface, 'untagged_vlan',
                                                                                      None) else None

        current_tagged_vlans = getattr(interface, 'tagged_vlans', [])
        # Handle cases where tagged_vlans might be None instead of an empty list
        current_tagged_ids = [v.id for v in current_tagged_vlans] if current_tagged_vlans else []

        needs_update = False
        audit_messages = []

        # Step 4: Check for Untagged VLAN changes
        if current_untagged_id != desired_untagged_id:
            # print(f"[{interface.name}] Untagged VLAN changed: {current_untagged_id} -> {desired_untagged_id}")
            msg = f"Untagged VLAN changed: {current_untagged_id} -> {desired_untagged_id}"
            print(f"[{interface.name}] {msg}")
            audit_messages.append(msg)
            interface.untagged_vlan = desired_untagged_id
            needs_update = True

        # Step 5: Check for Tagged VLAN changes using Python Sets
        current_set = set(current_tagged_ids)
        desired_set = set(desired_tagged_ids)

        if current_set != desired_set:
            removed = current_set - desired_set
            added = desired_set - current_set

            if removed:
                # print(f"[{interface.name}] Removing Tagged NetBox VLAN IDs: {removed}")
                msg = f"Removing Tagged NetBox VLAN IDs: {list(removed)}"
                print(f"[{interface.name}] {msg}")
                audit_messages.append(msg)
            if added:
                # print(f"[{interface.name}] Adding Tagged NetBox VLAN IDs: {added}")
                msg = f"Adding Tagged NetBox VLAN IDs: {list(added)}"
                print(f"[{interface.name}] {msg}")
                audit_messages.append(msg)

            interface.tagged_vlans = desired_tagged_ids
            needs_update = True

        # Step 6: Apply the changes
        if needs_update:
            # Set the 802.1Q mode properly based on the new desired state
            if desired_tagged_ids:
                interface.mode = 'tagged'
            elif desired_untagged_id:
                interface.mode = 'access'
            else:
                # If both are empty, we must clear the mode in NetBox
                interface.mode = ''

            try:
                interface.save()
                print(f"[{interface.name}] Successfully synced to NetBox.\n")
                logger.info(f"Interface {interface.name} synced: " + " | ".join(audit_messages))
            except Exception as e:
                print(f"[{interface.name}] Failed to save: {e}\n")
                logger.error(f"Failed to sync interface {interface.name}: {e}")
        else:
            # Optional: Comment this out if it makes your console output too noisy
            print(f"[{interface.name}] No changes needed. In sync.\n")
    return


def main():
    logger.info("--- Started execution of NetBox VLAN Importer ---")
    parser = argparse.ArgumentParser(description="Import VLANs into NetBox")
    parser.add_argument("input_file", help="JSON file generated by the VLAN parser.")
    parser.add_argument("-d", "--device", help="NetBox Device Name.")
    args = parser.parse_args()

    try:
        with open(args.input_file, 'r') as f:
            data = json.load(f)
            logger.info(f"Loaded JSON file: {args.input_file}")
    except Exception as e:
        print(f"Error reading JSON: {e}")
        logger.error(f"Error reading JSON file {args.input_file}: {e}")
        sys.exit(1)

    device_tag = data.get("device-tag")
    vlans = data.get("vlans", [])

    if not vlans:
        print("No VLANs found in JSON.")
        logger.warning("No VLANs found in parsed JSON. Exiting.")
        sys.exit(0)

    print(f"Connecting to NetBox...")
    # 1. Instantiate the single, shared NetBox connection
    nb = get_netbox_client()

    # Resolve Tag ID
    tag_obj = get_or_create_tag(nb, tag_name=device_tag)

    if not tag_obj:
        print(f"Error: Tag '{device_tag}' not found in NetBox DCIM.")
        logger.error(f"Fatal Error: Tag '{device_tag}' could not be found or created.")
        sys.exit(1)

    # Retrieve existing VLANs for current device tag - convert VIDs into str type
    existing_vlan_list_with_device_tag = list(nb.ipam.vlans.filter(tag=device_tag))

    # Create/Update VLANs into Netbox - Returns list of created + updated VLANs
    updated_vlan_list = add_update_vlan_list_to_netbox(nb, vlans, tag_obj)

    # Check for any VLANs changes for device tag before and after import
    print(f"\n--- Check potential VLANs to be removed from Tag: {tag_obj.name}")
    before_import = set(existing_vlan_list_with_device_tag)
    after_import = set(updated_vlan_list)
    vid_difference_after_import = before_import.difference(after_import)

    if not vid_difference_after_import:
        print(f"  [+] No VLANs to be removed from Tag: {tag_obj.name}\n")

    # Remove device tag if VLAN is not found in new configuration
    for missing_vlan in vid_difference_after_import:
        print(f"\n--- Processing removal of tag from VLAN: {missing_vlan.vid} (Name: {missing_vlan.name})")
        missing_vlan.tags.remove(tag_obj)
        try:
            missing_vlan.save()
            print("  [+] Tag Removal successful.")
            logger.info(f"Removed tag '{tag_obj.name}' from VLAN VID {missing_vlan.vid} (Name: {missing_vlan.name})")
        except Exception as e:
            print(f"  [!] Tag Removal failed: {e}")
            logger.error(f"Failed to remove tag '{tag_obj.name}' from VLAN VID {missing_vlan.vid}: {e}")

    # Sync VLAN Port mappings for device
    get_interfaces_from_device = list(nb.dcim.interfaces.filter(device=args.device))
    port_mappings = port_based_vlan_mapping(vlans)
    sync_vlan_port_mappings(get_interfaces_from_device, port_mappings, updated_vlan_list)

    logger.info("--- Finished execution of NetBox VLAN Importer ---")


if __name__ == "__main__":
    main()
