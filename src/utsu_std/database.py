import logging
from pathlib import Path
import sqlite3
import csv

from utsu_std.utils import generate_uuid, normalize_case, get_uoft_trunc_format, get_trunc_id

logger = logging.getLogger(__name__)

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
        raise e

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

def check_for_student(student: dict[str, str], cursor: sqlite3.Cursor):
    """
    Verify the provided student information against the stored database records.

    Args:
        cursor (Cursor): The database cursor to execute queries against.
        student (dict[str, str]): The student object containing the student's information to be verified.
        The student dictionary should contain the following keys:
            - "id" (optional): The full student ID.
            - "trun_id" (optional): The truncated student ID derived from the full ID.
            - "first_name": The student's first name.
            - "last_name": The student's last name.

    Returns:
        bool: True if the student information matches any stored records, False otherwise.
    """

    keys = student.keys()

    # check if id is supplied and derive trunc_id
    if "id" in keys and "trun_id" not in keys:
        student["trun_id"] = get_uoft_trunc_format(student["id"])

    # Ensure that the required student information fields are present
    required_fields = {"trun_id", "first_name", "last_name"}
    # Use subset math to determine if any required fields are missing
    if not required_fields.issubset(keys):
        missing_fields = required_fields - keys
        for field in missing_fields:
            logger.error(f"{field.replace('_', ' ').title()} is missing from the provided student information.")
        return False

    # query the database for the student information based on the required fields
    query = "SELECT * FROM students WHERE trun_id = ? AND first_name = ? AND last_name = ?"
    cursor.execute(query, (student["trun_id"], student["first_name"], student["last_name"]))
    matches = cursor.fetchall()

    return {"result": matches.__len__() == 1, "matches": matches}

def bulk_check_for_students(full_names: list[str], trunc_ids: list[str], cursor: sqlite3.Cursor,
                            log_sample: bool = False):
    """
    Check students against uoft_data by (trunc_id, full_name).

    Returns {"result": bool, "matches": [...uoft_data rows], "non_matches": [(full_name, trunc_id), ...]}.
    If log_sample is True, 5 rows from uoft_data are logged.
    """
    if log_sample:
        cursor.execute("SELECT * FROM uoft_data LIMIT 5")
        for sample_row in cursor.fetchall():
            logger.info(f"uoft_data sample: {sample_row}")

    cursor.execute("DROP TABLE IF EXISTS temp_chk_stds")
    cursor.execute("CREATE TEMP TABLE temp_chk_stds (trunc_id INTEGER, full_name TEXT)")

    cursor.executemany(
        "INSERT INTO temp_chk_stds (full_name, trunc_id) VALUES (?, ?)",
        [
            ( full_name, trunc_id )
            for full_name, trunc_id in zip(full_names, trunc_ids)
        ]
    )

    try:
        query = """
                SELECT s.*
                FROM uoft_data s
                INNER JOIN temp_chk_stds t
                ON s.trunc_id = t.trunc_id AND s.full_name = t.full_name
            """
        cursor.execute(query)
        matches = cursor.fetchall()

        cursor.execute("""
                SELECT t.full_name, t.trunc_id
                FROM temp_chk_stds t
                LEFT JOIN uoft_data s
                ON s.trunc_id = t.trunc_id AND s.full_name = t.full_name
                WHERE s.uuid IS NULL
            """)
        non_matches = cursor.fetchall()
    except Exception as e:
        cursor.execute("DROP TABLE IF EXISTS temp_chk_stds")
        logger.error(f"Error occurred during bulk check for students: {e}")
        matches = []
        non_matches = list(zip(full_names, trunc_ids))

    result = {"result": matches.__len__() == len(full_names), "matches": matches,
              "non_matches": non_matches}

    cursor.execute("DROP TABLE IF EXISTS temp_chk_stds")

    return result

