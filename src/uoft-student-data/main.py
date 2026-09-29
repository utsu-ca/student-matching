import argparse
import csv

from utsu_std.utils import normalize_case, setup_logging, load_config_from_json, merge_config_with_args
# 
# 
# 

def main():
    # Implement the main functionality here
    pass


def run_verification_of_csv(csv_path: str, db_path: str):
    # Implement the verification logic here

    # read the CSV file containing student data

    with open(csv_path, newline='') as csvfile:
        reader = csv.DictReader(csvfile)
        # check header
        expected_headers = {"Student ID", "First Name", "Last Name", "Email"}

        # normalize the header names to a set for comparison
        norm_expected_headers = {normalize_case(field) for field in expected_headers}
        actual_headers = {normalize_case(field) for field in reader.fieldnames}

        if norm_expected_headers.issubset(actual_headers) is False:
            raise ValueError(f"CSV header does not match expected headers: {norm_expected_headers}, difference: {norm_expected_headers - actual_headers}")
        
        # batch processing of 50 students at a time
        batch = []
        for row in reader:
            batch.append(row)
            if len(batch) == 50:
                # Perform verification logic for each batch
                
                # query the database for exact matches

                exact_bulk_query()

                for student in batch:
                    pass
                batch = []

        # Process any remaining students in the last batch
        if batch:
            for student in batch:
                pass

    pass


# =========================
# CLI Entrypoint
# =========================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="")
    parser.add_argument("--verify_student", default="./verify.csv",
                        help="Verify that the provided path to a CSV file matches the stored student data")
    
    parser.add_argument("--db", default="./db.sqlite",
                            help="Path to the database file containing student data")

    parser.add_argument("--parse_students", default="./students.csv",
                        help="Path to the CSV file containing student data to be parsed")

    parser.add_argument("--verbosity", default="INFO",
                        help="Set the logging verbosity level")
    parser.add_argument("--log_file", default="./app.log",
                        help="Path to the log file")
    parser.add_argument("--dry_run", default=False, action="store_true",
                        help="Run the script in dry run mode without making any changes")
        
    
    parser.add_argument("--config", default="./config.json",
                        help="Path to a JSON config file with settings")
    parser.add_argument("--save-config", default=False, action="store_true",
                        help="Save the resolved configuration back to the JSON file")

    args = parser.parse_args()
    args = merge_config_with_args(args, parser)

    setup_logging(args.verbosity, args.log_file, args.dry_run)

    main()