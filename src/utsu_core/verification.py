import csv
import logging
from pathlib import Path


logger = logging.getLogger(__name__)


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
            print(header)
            for row in f:
                # remove newline
                row = [_.strip('" ') for _ in row.strip().split(",")]
                if len(row) >= 2:
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
    f_in = open(csv_file, newline='')
    reader = csv.reader(f_in)
    headers = next(reader)

    # check if required columns are present in the headers
    if not set(required_col).issubset(set(headers)):
        missing_cols = set(required_col) - set(headers)
        raise ValueError(f"Missing required names in columns: {missing_cols}")

    # replace current headers with new names
    new_headers = []
    for key in headers:
        if key in name_table_mapping:
            new_headers.append(name_table_mapping[key])
        else:
            print(key)
            logger.info(f" {key} not in mapping")

    # replace reader
    return csv.DictReader(f_in, fieldnames=new_headers)