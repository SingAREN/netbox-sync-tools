import subprocess
import sys
import os

from logger_setup import get_configured_logger
from config_loader import get_batch_config, get_project_root

logger = get_configured_logger('batch_runner')

PROJECT_ROOT = get_project_root()
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))

# Create an environment copy that includes the src/ directory in the PYTHONPATH
custom_env = os.environ.copy()
custom_env["PYTHONPATH"] = CURRENT_DIR


def execute_parser(conf_fp, tag, output_fp):
    parser_script = os.path.join(CURRENT_DIR, 'parsers', 'vlan_parser.py')

    # Passing a list completely bypasses shell parsing, protecting your Windows backslashes and spaces!
    tokens = [
        sys.executable,
        parser_script,
        conf_fp,
        '-t', tag,
        '-o', output_fp
    ]

    try:
        results = subprocess.run(tokens, capture_output=True, text=True, check=True, env=custom_env)
        print(f"  [+] Parser Output: {results.stdout.strip()}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"  [!] Parser failed with return code: {e.returncode}")

        # Combine both stdout and stderr so we don't miss any error messages
        error_details = f"STDOUT: {e.stdout.strip()} | STDERR: {e.stderr.strip()}"
        print(f"  [!] Details: {error_details}")

        logger.error(f"Parser failed for {conf_fp}: {error_details}")
        return False


def execute_importer(output_fp, device):
    importer_script = os.path.join(CURRENT_DIR, 'importers', 'vlan_importer.py')

    tokens = [
        sys.executable,
        importer_script,
        output_fp,
        '-d', device
    ]

    try:
        results = subprocess.run(tokens, capture_output=True, text=True, check=True, env=custom_env)
        print(f"  [+] Importer Output: {results.stdout.strip()}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"  [!] Importer failed with return code: {e.returncode}")

        error_details = f"STDOUT: {e.stdout.strip()} | STDERR: {e.stderr.strip()}"
        print(f"  [!] Details: {error_details}")

        logger.error(f"Importer failed for device {device}: {error_details}")
        return False


def main():
    logger.info("Starting Batch Execution")
    config = get_batch_config()

    # Tracking dictionaries for the summary report
    summary = {
        'successful': [],
        'failed': []
    }

    for each_section in config.sections():
        # Read parameters (Notice the keys are now FILENAME instead of FILEPATH)
        config_filename = config.get(each_section, 'CONFIGURATION_FILENAME').strip('"\'')
        tag = config.get(each_section, 'TAG').strip('"\'')
        output_filename = config.get(each_section, 'OUTPUT_FILENAME').strip('"\'')
        device = config.get(each_section, 'DEVICE').strip('"\'')

        # --- NEW LOGIC: Auto-resolve absolute paths ---
        conf_fp = os.path.join(PROJECT_ROOT, 'data', 'network_configs', config_filename)
        output_fp = os.path.join(PROJECT_ROOT, 'data', 'parser_outputs', output_filename)

        print(f"\n{'=' * 50}")
        print(f"Processing Device: {device} ({each_section})")
        print(f"Input: {conf_fp}")
        print(f"{'=' * 50}")

        logger.info(f"Processing batch section: {each_section} for device {device}")

        # Step 1: Run Parser
        print("-> Running Parser...")
        parser_success = execute_parser(conf_fp, tag, output_fp)

        if not parser_success:
            summary['failed'].append({'device': device, 'reason': 'Parser Error'})
            continue  # Skip importer if parser fails

        # Step 2: Run Importer
        print("-> Running Importer...")
        importer_success = execute_importer(output_fp, device)

        if not importer_success:
            summary['failed'].append({'device': device, 'reason': 'Importer Error'})
            continue

        # If both succeeded, record success
        summary['successful'].append(device)

    # --- Print Final Summary Report ---
    print("\n\n" + "#" * 50)
    print("### BATCH EXECUTION SUMMARY REPORT ###")
    print("#" * 50)

    total_run = len(summary['successful']) + len(summary['failed'])
    print(f"Total Devices Processed : {total_run}")
    print(f"Successful Executions   : {len(summary['successful'])}")
    print(f"Failed Executions       : {len(summary['failed'])}")

    if summary['successful']:
        print("\n--- Successful Devices ---")
        for dev in summary['successful']:
            print(f"  * {dev}")

    if summary['failed']:
        print("\n--- Failed Devices ---")
        for fail_record in summary['failed']:
            print(f"  * {fail_record['device']} (Failed Stage: {fail_record['reason']})")

    print("#" * 50 + "\n")
    logger.info("Finished Batch Execution")


if __name__ == '__main__':
    main()
