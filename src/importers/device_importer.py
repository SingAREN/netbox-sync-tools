import argparse
import sys
import re
from logger_setup import get_configured_logger
from netbox_client import get_netbox_client

logger = get_configured_logger('device_importer')


def to_slug(text):
    """Converts a string into a URL-friendly NetBox slug."""
    return re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')


def get_or_create_site(nb, site_name):
    site = nb.dcim.sites.get(name=site_name)
    if site:
        return site

    logger.info(f"Creating new Site: {site_name}")
    print(f"  [+] Creating missing Site: '{site_name}'")
    return nb.dcim.sites.create(
        name=site_name,
        slug=to_slug(site_name),
        status='active'
    )


def get_or_create_manufacturer(nb, mfg_name):
    mfg = nb.dcim.manufacturers.get(name=mfg_name)
    if mfg:
        return mfg

    logger.info(f"Creating new Manufacturer: {mfg_name}")
    print(f"  [+] Creating missing Manufacturer: '{mfg_name}'")
    return nb.dcim.manufacturers.create(
        name=mfg_name,
        slug=to_slug(mfg_name)
    )


def get_or_create_device_role(nb, role_name):
    role = nb.dcim.device_roles.get(name=role_name)
    if role:
        return role

    logger.info(f"Creating new Device Role: {role_name}")
    print(f"  [+] Creating missing Device Role: '{role_name}'")
    return nb.dcim.device_roles.create(
        name=role_name,
        slug=to_slug(role_name),
        color='9e9e9e'  # Default generic grey
    )


def get_or_create_device_type(nb, model_name, mfg_id):
    device_type = nb.dcim.device_types.get(model=model_name)
    if device_type:
        return device_type

    logger.info(f"Creating new Device Type: {model_name}")
    print(f"  [+] Creating missing Device Type: '{model_name}'")
    return nb.dcim.device_types.create(
        manufacturer=mfg_id,
        model=model_name,
        slug=to_slug(model_name)
    )


def sync_device(nb, args):
    """Ensures all prerequisites exist, then creates or updates the Device."""
    print(f"--- Synchronizing Device: {args.device} ---")

    # 1. Resolve Prerequisites
    site = get_or_create_site(nb, args.site)
    mfg = get_or_create_manufacturer(nb, args.manufacturer)
    role = get_or_create_device_role(nb, args.role)
    dev_type = get_or_create_device_type(nb, args.type, mfg.id)

    # 2. Check Device Existence
    device = nb.dcim.devices.get(name=args.device)

    if device:
        print(f"  [*] Device '{args.device}' already exists in NetBox. Checking for drift...")
        updates = {}

        # Check if attributes differ (handling PyNetBox object lookups)
        if getattr(device.device_type, 'id', None) != dev_type.id:
            updates['device_type'] = dev_type.id
            print(f"      - Drift detected: Updating Device Type to '{args.type}'")

        # NetBox 3.6+ changed 'device_role' to 'role'. This safely handles both.
        current_role = getattr(device, 'role', getattr(device, 'device_role', None))
        if getattr(current_role, 'id', None) != role.id:
            if hasattr(device, 'role'):
                updates['role'] = role.id
            else:
                updates['device_role'] = role.id
            print(f"      - Drift detected: Updating Role to '{args.role}'")

        if getattr(device.site, 'id', None) != site.id:
            updates['site'] = site.id
            print(f"      - Drift detected: Updating Site to '{args.site}'")

        # 3a. Update existing device
        if updates:
            device.update(updates)
            print("  [+] Device updated successfully.")
            logger.info(f"Updated Device {args.device} with new attributes: {updates}")
        else:
            print("  [+] Device is already up-to-date.")

        return device

    # 3b. Create new Device
    logger.info(f"Creating new Device: {args.device}")
    print(f"  [+] Provisioning new Device: '{args.device}'")
    device = nb.dcim.devices.create(
        name=args.device,
        device_type=dev_type.id,
        role=role.id,
        site=site.id,
        status='active'
    )
    return device


def main():
    parser = argparse.ArgumentParser(description="Synchronize Devices in NetBox")
    parser.add_argument("-d", "--device", required=True, help="Device Name")
    parser.add_argument("-m", "--manufacturer", required=True, help="Manufacturer Name")
    parser.add_argument("-t", "--type", required=True, help="Device Type (Model)")
    parser.add_argument("-r", "--role", required=True, help="Device Role")
    parser.add_argument("-s", "--site", required=True, help="Site Name")

    args = parser.parse_args()
    nb = get_netbox_client()

    try:
        sync_device(nb, args)
    except Exception as e:
        logger.error(f"Device sync failed for {args.device}: {e}")
        print(f"  [!] Fatal Error syncing device: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
