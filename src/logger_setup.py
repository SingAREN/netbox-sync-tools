import os
import logging


def get_configured_logger(logger_name):
    """Initializes the base configuration and returns a named logger."""

    # Calculate the path strictly relative to this specific file
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(current_dir, '..'))
    log_file = os.path.join(project_root, 'logs', 'sync_audit.log')

    # Ensure the logs directory exists just in case
    os.makedirs(os.path.dirname(log_file), exist_ok=True)

    logging.basicConfig(
        filename=log_file,
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    return logging.getLogger(logger_name)

