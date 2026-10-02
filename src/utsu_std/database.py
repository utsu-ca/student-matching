import logging
from pathlib import Path
import sqlite3
import csv

from utsu_std.utils import generate_uuid, strip_truncated_student_number


logger = logging.getLogger(__name__)

def create_db(filepath: Path):
    conn = sqlite3.connect(filepath)
    return conn

def get_connection(filepath : Path):
    return sqlite3.connect(filepath)


def import_csv_to_db(csv_file: Path, table_name: str, conn: sqlite3.Connection):
    """
    Function to import CSV data into the specified table in the database.
    Adds an import_date column to track when the data was imported.
    """
    try: 
        cursor = conn.cursor()
        with open(csv_file, newline='') as f:
            reader = csv.reader(f)
            headers = next(reader) + ["import_date"]
            placeholders = ', '.join(['?'] * len(headers))
            query = f"INSERT INTO {table_name} ({', '.join(headers)}) VALUES ({placeholders})"
            for row in reader:
                cursor.execute(query, row + ["CURRENT_TIMESTAMP"])
        conn.commit()
        logger.info(f"Data imported successfully into {table_name}")
    except Exception as e:
        logger.error(f"An error occurred: {e}")
        conn.rollback()
    conn.close()


def import_uoft_data(conn: sqlite3.Connection, csv_file: Path = Path("./data/uoft_data.csv")):
    """
    Function to import UofT data from a CSV file into the database.
    Returns True if the import is successful.
    """
    logger.info(f"Creating uoft_data table if it does not exist")
    try:
        script = open("./schema/uoft_data.sql").read()
        conn.executescript(script)
    except Exception as e:
        logger.error(f"An error occurred while creating uoft_data table: {e}")
        conn.rollback()
        return False

    logger.info(f"Importing UofT data from {csv_file}")
    preprocessed_csv_file = preprocess_uoft_csv(csv_file)
    logger.info(f"Preprocessed UofT CSV file: {csv_file} -> {preprocessed_csv_file}")
    import_csv_to_db(preprocessed_csv_file, "uoft_data", conn)

    logger.info(f"Indexing uoft_data table, please wait...")
    # apply index on Last Name column, followed by Truncated Student Number
    cursor = conn.cursor()
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_last_name ON uoft_data(`last_name`)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_trunc_id ON uoft_data(`trunc_id`)")
    conn.commit()
    logger.info(f"Indexes applied successfully on uoft_data table")

    return True

def preprocess_uoft_csv(csv_file: Path):
    # Preprocess the UofT CSV file to ensure it meets the required format before importing into the database.

    # step one: ensure required columns are present in the CSV file

    # ensure the CSV file exists
    if not csv_file.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_file}")
    
    required_col = ("First Name", "Last Name", "Truncated Student Number", "Faculty", "Division")
    processed_csv_file = Path(str(csv_file.stem) + "_processed.csv")
    with open(csv_file, newline='') as f_in, open(processed_csv_file, 'w', newline='') as f_out:
        reader = csv.reader(f_in)
        headers = next(reader)

        # check if required columns are present in the headers
        if not set(required_col).issubset(set(headers)):
            missing_cols = set(required_col) - set(headers)
            # clean up after self
            f_out.close()
            processed_csv_file.unlink()

            raise ValueError(f"Missing required columns: {missing_cols}")

        # prepare the CSV writer with the expected headers
        expected_headers: tuple[str, ...] = ("uuid", "last_name", "first_name", "trunc_id", "faculty", "division")
        writer = csv.DictWriter(f_out, fieldnames=expected_headers)
        writer.writeheader()

        # step two: process rows
        for row in reader:
            # remove whitespace per value
            row = [_.strip() for _ in row]

            # using dictionary so order doesn't matter
            row_dict = {}

            trunc_id_indx = headers.index("Truncated Student Number")
            last_name_indx = headers.index("Last Name")
            first_name_indx = headers.index("First Name")
            faculty_indx = headers.index("Faculty")
            division_indx = headers.index("Division")

            row_dict["trunc_id"] = row[trunc_id_indx].strip("x")
            row_dict["last_name"] = row[last_name_indx]
            row_dict["first_name"] = row[first_name_indx]
            row_dict["faculty"] = row[faculty_indx]
            row_dict["division"] = row[division_indx]
            # generate UUID; should be safe for UUID as .values() returns in insertion order.
            row_dict["uuid"] = generate_uuid("".join(row_dict.values()))

            writer.writerow(row_dict)
    return processed_csv_file
preprocess_uoft_csv(Path("../../tests/utsu_std/test_data/fake_uoft_data.csv"))

def export_db_to_csv(table_name: str, csv_file: Path, conn: sqlite3.Connection):
    try:
        cursor = conn.cursor()
        cursor.execute(f"SELECT * FROM {table_name}")
        rows = cursor.fetchall()
        headers = [description[0] for description in cursor.description]

        with open(csv_file, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            writer.writerows(rows)

        logger.info(f"Data exported successfully from {table_name} to {csv_file}")
    except Exception as e:
        logger.error(f"An error occurred: {e}")

def return_unique_values(table_name: str, column_name: str, conn: sqlite3.Connection):
    try:
        cursor = conn.cursor()
        cursor.execute(f"SELECT DISTINCT {column_name} FROM {table_name}")
        rows = cursor.fetchall()
        return [row[0] for row in rows]
    except Exception as e:
        logger.error(f"An error occurred: {e}")
        return []

def return_all_values(table_name: str, column_name: str, conn: sqlite3.Connection):
    try:
        cursor = conn.cursor()
        cursor.execute(f"SELECT {column_name} FROM {table_name}")
        rows = cursor.fetchall()
        return [row[0] for row in rows]
    except Exception as e:
        logger.error(f"An error occurred: {e}")
        return []