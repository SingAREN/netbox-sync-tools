import requests
import pynetbox
import re


from config_loader import get_netbox_config
from logger_setup import get_configured_logger

logger = get_configured_logger('netbox_client')


def get_netbox_client():
    """Initializes and returns an authenticated pynetbox API client."""

    nb_settings = get_netbox_config()

    logger.info(f"Initializing NetBox client for {nb_settings['url']}")
    nb = pynetbox.api(url=nb_settings['url'], token=nb_settings['token'])

    if nb_settings['disable_tls']:
        session = requests.Session()
        session.verify = False
        import urllib3
        urllib3.disable_warnings()
        nb.http_session = session

    return nb


def get_or_create_tag(nb, tag_name, color="ffeb3b"):
    """
    Fetches a Netbox tag by name, or creates it with a specified hex color if missing.
    """
    tag = nb.extras.tags.get(name=tag_name)

    if tag:
        return tag

    logger.info(f"Tag '{tag_name}' not found. Creating it...")
    slug = re.sub(r'[^a-z0-9]+', '-', tag_name.lower()).strip('-')

    try:
        tag = nb.extras.tags.create(
            name=tag_name,
            slug=slug,
            color=color,
            description="Auto-created by NetBox sync tools"
        )
        logger.info(f"Created new NetBox Tag '{tag_name}' (ID: {tag.id})")
        return tag
    except Exception as e:
        logger.error(f"Failed to create NetBox Tag '{tag_name}': {e}")
        return None
