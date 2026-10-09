import csv
import logging
import sqlite3
from pathlib import Path


logger = logging.getLogger(__name__)


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
        list(zip(full_names, trunc_ids))
    )

    try:
        cursor.execute("""
                SELECT s.*
                FROM uoft_data s
                INNER JOIN temp_chk_stds t
                ON s.trunc_id = t.trunc_id AND s.full_name = t.full_name
            """)
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
        logger.error(f"Error occurred during bulk check for students: {e}")
        matches = []
        non_matches = list(zip(full_names, trunc_ids))

    result = {"result": len(matches) == len(full_names), "matches": matches,
              "non_matches": non_matches}

    cursor.execute("DROP TABLE IF EXISTS temp_chk_stds")

    return result


def construct_lookup_tables(mapping_file: Path) -> list[dict[str, str]]:
    # ensure the file exists
    if not mapping_file.exists():
        raise FileNotFoundError(f"Mapping file not found: {mapping_file}")

    name_table_mapping = {}
    table_name_mapping = {}
    try:
        # the csv module handles quoted commas; skipinitialspace allows `"a", "b"` with a space after the comma
        with open(mapping_file, 'r', newline='', encoding='utf-8-sig') as f:
            reader = csv.reader(f, skipinitialspace=True)
            header = next(reader, [])  # skip the header row
            logger.info(f"Processing lookup table from {mapping_file}; header: {header}")
            for row in reader:
                row = [_.strip() for _ in row]
                if len(row) >= 2 and row[0]:
                    name_table_mapping[row[0]] = row[1]
                    table_name_mapping[row[1]] = row[0]
    except Exception as e:
        logger.error(f"An error occurred: {e}")

    return [name_table_mapping, table_name_mapping]


def setup_reader(csv_file: Path, mapping_file: Path):
    name_table_mapping, table_name_mapping = construct_lookup_tables(mapping_file)

    # ensure the CSV file exists
    if not csv_file.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_file}")

    required_col = name_table_mapping.keys()
    f_in = open(csv_file, newline='', encoding='utf-8-sig')
    reader = csv.reader(f_in)
    headers = next(reader)

    # check if required columns are present in the headers; padding such as the form's "Faculty " is ignored
    headers = [h.strip() for h in headers]
    if not set(required_col).issubset(set(headers)):
        missing_cols = set(required_col) - set(headers)
        raise ValueError(f"Missing required names in columns: {missing_cols}")

    # replace current headers with new names; columns not in the mapping keep their original header so
    # the remaining columns stay aligned
    new_headers = []
    for key in headers:
        if name_table_mapping.get(key):
            new_headers.append(name_table_mapping[key])
        else:
            new_headers.append(key)
            logger.debug(f" {key} not in mapping; keeping its original name")

    # replace reader
    return csv.DictReader(f_in, fieldnames=new_headers)