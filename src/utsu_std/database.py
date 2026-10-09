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

def construct_lookup_tables(mapping_file: Path) -> list[dict[str, str]]:
    # ensure the file exists
    if not mapping_file.exists():
        raise FileNotFoundError(f"Mapping file not found: {mapping_file}")

    name_table_mapping = {}
    table_name_mapping = {}
    try:
        with open(mapping_file, 'r') as f:
            header = f.readline()  # skip the header row
            logger.info(f"Processing lookup table from {mapping_file}; header: {header}")
            for row in f:
                row = row.strip().split(",")
                if len(row) >= 2:
                    name_table_mapping[row[0]] = row[1]
                    table_name_mapping[row[1]] = row[0]
    except Exception as e:
        logger.error(f"An error occurred: {e}")

    return [name_table_mapping, table_name_mapping]
