import argparse
import csv
import logging
import sqlite3
from pathlib import Path

from utsu_core.Importing_data import import_uoft_data, preprocess_uoft_csv
from utsu_core.senate import verify_senators
from utsu_std.database import bulk_check_for_students, get_connection
from utsu_std.utils import get_trunc_id, normalize_case, normalize_name, setup_logging, load_and_merge_config


logger = logging.getLogger(__name__)

def main(cfg):
    # connect database
    db = get_connection(cfg['db'])

    # check if uoft_data exists
    cursor = db.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='uoft_data';")
    test = cursor.fetchone()
    # if path for new data is provided, or no data is found
    if cfg['import_uoft_data'] or not test:
        if not test:
            logger.info("Table 'uoft_data' does not exist in the database.")
        if not cfg['import_uoft_data']:
            logger.error("Application is missing UofT student data but no import file is specified in the configuration.")
            raise ValueError("Application is missing UofT student data but no import file is specified in the configuration.")
        else:
            logger.info("Importing UofT student data from the specified file.")
            # Implement the import logic here, e.g., read the CSV and populate the database
            uoft_data_path = Path(cfg['import_uoft_data'])
            # check existence
            if uoft_data_path.exists():
                import_uoft_data(db, uoft_data_path)
            else:
                logger.error(f"File not found: {uoft_data_path}" )
                quit()


    # Implement the main functionality here
    verify_senators(cfg['verify_student'], db.cursor(), log_sample=cfg.get('log_sample', False))
    pass


def run_verification_of_csv(csv_path: str, db_path: str):
    # Implement the verification logic here

    # read the CSV file containing student data

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    with open(csv_path, newline='') as csvfile:
        reader = csv.DictReader(csvfile)
        # check header
        expected_headers = {"Student Number", "First Name", "Last Name", "Email"}

        # normalize the header names to a set for comparison
        norm_expected_headers = {normalize_case(field) for field in expected_headers}
        actual_headers = {normalize_case(field) for field in reader.fieldnames} # type: ignore

        if not norm_expected_headers.issubset(actual_headers):
            raise ValueError(f"CSV header does not match expected headers: {norm_expected_headers}, difference: {norm_expected_headers - actual_headers}")
        
        # batch processing of 50 students at a time
        full_names = []
        trunc_ids = []
        for row in reader:
            full_names.append(normalize_name(row['First Name'], row['Last Name']))
            trunc_ids.append(get_trunc_id(row['Student ID']))

            if len(full_names) == 50:
                # Perform verification logic for each batch
                
                # query the database for exact matches
                results = bulk_check_for_students(full_names, trunc_ids, cursor)

                for row in results:
                    print(row)
                full_names = []
                trunc_ids = []
                quit(0)

        # Process any remaining students in the last batch
        if full_names:
            for full_name, trunc_id in zip(full_names, trunc_ids):
                results = bulk_check_for_students([full_name], [trunc_id], cursor)
                for row in results:
                    print(row)

    pass



# =========================
# CLI Entrypoint
# =========================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="")
    parser.add_argument("--verify_student", default="../../verify.csv",
                        help="Verify that the provided path to a CSV file matches the stored student data")
    
    parser.add_argument("--db", default="../../secrets/db.sqlite",
                            help="Path to the database file containing student data")

    parser.add_argument("--import_uoft_data", default="../../fake_uoft_data.csv",
                        help="Path to the CSV file containing student data to be parsed")

    parser.add_argument("--verbosity", default="TRACE",
                        help="Set the logging verbosity level")
    parser.add_argument("--log_file", default="../../app.log",
                        help="Path to the log file")
    parser.add_argument("--log_sample", default=True, action="store_true",
                        help="Log 5 sample rows from uoft_data during verification")
    parser.add_argument("--dry_run", default=False, action="store_true",
                        help="Run the script in dry run mode without making any changes")
        
    
    parser.add_argument("--config", default="../../config.json",
                        help="Path to a JSON config file with settings")

    args = parser.parse_args()
    args = load_and_merge_config(args, parser)
    setup_logging(args)

    main(args)