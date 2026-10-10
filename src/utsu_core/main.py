import argparse
import csv
import logging
import sqlite3
import sys
from pathlib import Path

from utsu_core.importing_data import import_uoft_data, preprocess_uoft_csv
from utsu_core.senate import verify_senators
from utsu_core.agm import process_agm
from utsu_core.sap import merge_reviews, process_sap
from utsu_core.seating import run_seating
from utsu_core.verification import bulk_check_for_students
from utsu_std.database import get_connection
from utsu_std.utils import absfile, normalize_case, setup_logging, load_and_merge_config
from utsu_std.parsing_utils import get_trunc_id, normalize_name

logger = logging.getLogger(__name__)

def main(cfg):
    # connect database
    db = get_connection(cfg['db'])

    if cfg.get('merge_reviews'):
        result = merge_reviews(db, output_dir=cfg.get('output_dir', 'secrets/output'))
        print(f"Merged SABP ratings: {result['counts']}")
        return

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
    program = cfg.get('program', 'all')
    if program in ('senate', 'all'):
        verify_senators(cfg['verify_student'], db.cursor(), log_sample=cfg.get('log_sample', False),
                        output_dir=cfg.get('output_dir', 'secrets/output'))

        seats_file = absfile(cfg.get('seats_file', 'data/seats_senate.csv'))
        if seats_file.exists():
            run_seating(Path(absfile(cfg.get('output_dir', 'secrets/output'))) / "verified.csv", seats_file,
                        cfg.get('output_dir', 'secrets/output'), cfg.get('seed', 2026))
        else:
            logger.warning(f"Seats file not found, skipping seating: {seats_file}")

    if program in ('sap', 'all'):
        if cfg.get('sap_file'):
            process_sap(cfg['sap_file'], db, output_dir=cfg.get('output_dir', 'secrets/output'),
                        batch_size=cfg.get('batch_size', 50), reviewers=cfg.get('reviewers', ''))
        elif program == 'sap':
            raise ValueError("No SABP form export given; set --sap_file")

    if program in ('agm', 'all'):
        if cfg.get('agm_file'):
            process_agm(cfg['agm_file'], db, output_dir=cfg.get('output_dir', 'secrets/output'))
        elif program == 'agm':
            raise ValueError("No AGM RSVP export given; set --agm_file")
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



TESTING_DIR = "testing"
PATH_KEYS = ("verify_student", "sap_file", "agm_file", "import_uoft_data", "db", "log_file", "output_dir", "seats_file")


def resolve_paths(cfg: dict) -> dict:
    """Make every path setting absolute. Relative paths are taken from the project root, not the working directory."""
    for key in PATH_KEYS:
        if cfg.get(key):
            cfg[key] = str(absfile(cfg[key]))
    return cfg


def build_fake_data() -> None:
    """Write the fake roster and form exports to testing/output/. Seeded, so every run produces the same files."""
    testing = str(absfile(TESTING_DIR))
    if testing not in sys.path:
        sys.path.insert(0, testing)
    from generate_fake_data import generate_all
    generate_all()


def apply_testing_mode(args, parser) -> dict:
    """
    Settings for --testing: generate the fake data, read it, and write the database, logs and results, all in
    testing/output/. config.json is neither read nor written, and a fresh database is built every run.
    Flags given explicitly on the command line still win over these defaults.
    """
    out = TESTING_DIR + "/output"
    defaults = {
        "verify_student": f"{out}/fake_senator.csv",
        "sap_file": f"{out}/fake_sabp.csv",
        "agm_file": f"{out}/fake_agm.csv",
        "reviewers": "Reviewer_A,Reviewer_B,Reviewer_C",
        "import_uoft_data": f"{out}/fake_uoft_data.csv",
        "db": f"{out}/test.sqlite",
        "log_file": f"{out}/test.log",
        "output_dir": out,
    }
    cfg = vars(args).copy()
    for key, value in defaults.items():
        if cfg[key] == parser.get_default(key):
            cfg[key] = value
    resolve_paths(cfg)
    absfile(out).mkdir(parents=True, exist_ok=True)
    if not cfg.get("merge_reviews"):  # merging reads the reviewer assignments saved by the last run
        build_fake_data()
        Path(cfg["db"]).unlink(missing_ok=True)
    return cfg


# =========================
# CLI Entrypoint
# =========================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="")
    parser.add_argument("--testing", default=True, action="store_true",
                        help="Generate the fake data, run on it, and write everything to testing/output/")
    parser.add_argument("--verify_student", default="secrets/verify.csv",
                        help="Verify that the provided path to a CSV file matches the stored student data")
    parser.add_argument("--program", default="all", choices=["senate", "sap", "agm", "all"],
                        help="Which program to process: Senate applications, Student Aid Bursary (SABP), AGM voter "
                             "RSVPs, or all of them")
    parser.add_argument("--agm_file", default="",
                        help="AGM voter RSVP export (CSV) to verify")
    parser.add_argument("--sap_file", default="",
                        help="SABP form export (CSV) to verify, score and cut into review batches")
    parser.add_argument("--batch_size", default=50, type=int,
                        help="Applications per anonymized SABP review batch")
    parser.add_argument("--reviewers", default="",
                        help="Comma separated committee members (two or more); each SABP batch is assigned to two")
    parser.add_argument("--merge_reviews", default=False, action="store_true",
                        help="Merge the completed reviewer sheets into sap_merged_ratings.csv instead of processing")
    
    parser.add_argument("--db", default="secrets/db.sqlite",
                            help="Path to the database file containing student data")

    parser.add_argument("--import_uoft_data", default="secrets/uoft_data.csv",
                        help="Path to the CSV file containing student data to be parsed")

    parser.add_argument("--verbosity", default="TRACE",
                        help="Set the logging verbosity level")
    parser.add_argument("--log_file", default="secrets/app.log",
                        help="Path to the log file")
    parser.add_argument("--seats_file", default="data/seats_senate.csv",
                        help="CSV of seats per constituency (columns: constituency,division,seats)")
    parser.add_argument("--seed", default=2026, type=int,
                        help="Seed for tie-breaking in seat assignment; the same seed reproduces the same result")
    parser.add_argument("--output_dir", default="secrets/output",
                        help="Directory (relative to the project root) for verified.csv and unverified.csv")
    parser.add_argument("--log_sample", default=True, action="store_true",
                        help="Log 5 sample rows from uoft_data during verification")
    parser.add_argument("--dry_run", default=False, action="store_true",
                        help="Run the script in dry run mode without making any changes")
        
    
    parser.add_argument("--config", default="config.json",
                        help="Path to a JSON config file with settings (relative paths are from the project root)")

    args = parser.parse_args()
    args = apply_testing_mode(args, parser) #if args.testing else load_and_merge_config(args, parser)
    setup_logging(args)

    main(args)