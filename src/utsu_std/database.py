import logging
from pathlib import Path
import sqlite3
import csv


logger = logging.getLogger(__name__)

def create_db(filepath: Path):
    conn = sqlite3.connect(filepath)
    return conn

def get_connection(filepath : Path):
    return sqlite3.connect(filepath)

"""
    Function to import CSV data into the specified table in the database.
    Adds an import_date column to track when the data was imported.
"""
def import_csv_to_db(csv_file: Path, table_name: str, conn: sqlite3.Connection):
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

"""
    Function to import UofT data from a CSV file into the database.
    Checks if the CSV headers match the expected headers for the uoft_data table.
    Returns True if the import is successful.
    Raises ValueError if the CSV headers do not match the expected headers.
"""
def import_uoft_data(csv_file: Path, conn: sqlite3.Connection):
    headers = None

    # Grab the headers from the CSV file
    with open(csv_file, newline='') as f:
        reader = csv.reader(f)
        headers = next(reader)

    # Define the expected headers for the uoft_data table
    # Last Name, First Name, Truncated Student Number, Faculty, Organization, Division
    expected_headers = ["Last Name", "First Name", "Truncated Student Number", "Faculty", "Organization", "Division"]
    
    # Check if all the expected headers are present in the CSV file
    if set(expected_headers) <= set(headers):
        import_csv_to_db(csv_file, "uoft_data", conn)

        logger.info(f"Indexing uoft_data table, please wait...")
        # apply index on Last Name column, followed by Truncated Student Number
        cursor = conn.cursor()
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_last_name ON uoft_data(`Last Name`)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_truncated_student_number ON uoft_data(`Truncated Student Number`)")
        conn.commit()
        logger.info(f"Indexes applied successfully on uoft_data table")

        return True
    
    raise ValueError(f"CSV headers do not match expected headers for uoft_data table: {expected_headers}")

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

def exact_bulk_query(batch: list[dict], conn: sqlite3.Connection):
    """Perform an exact bulk query on the uoft_data table for the given batch of students.
    
    Args:
        batch (list[dict]): A list of student dictionaries containing the keys "First Name", "Last Name", and "Truncated Student Number".
        conn (sqlite3.Connection): The SQLite database connection.

    Returns:
        list: A list of rows from the uoft_data table that match the given batch of students.
    """

    # Implement the exact bulk query logic here

    cursor = conn.cursor()
    "First Name", "Last Name", "Truncated Student Number"
    columns = ["First Name", "Last Name", "Truncated Student Number"]

    # check keys exist in batch
    for student in batch:
        for col in columns:
            if col not in student:
                raise ValueError(f"Missing key '{col}' in student dictionary: {student}")

    # Construct the WHERE clause for the exact match query
    where_clauses = []
    for student in batch:
        conditions = [f"`{col}` = ?" for col in columns]
        where_clauses.append(f"({' AND '.join(conditions)})")

    query = f"SELECT * FROM uoft_data WHERE {' OR '.join(where_clauses)}"
    values = [student[col] for student in batch for col in columns]

    cursor.execute(query, values)
    results = cursor.fetchall()

    return results