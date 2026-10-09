import csv
import logging
import sqlite3
from pathlib import Path

from utsu_core.verification import setup_reader, bulk_check_for_students
from utsu_std.utils import get_trunc_id, normalize_case

logger = logging.getLogger(__name__)

def verify_senators(csv_file: Path, cursor: sqlite3.Cursor, log_sample: bool = False):
    mapping_file: Path = Path("../../data/lookup_table_senate.csv")
    if type(csv_file) == str:
        csv_file = Path(csv_file)
    senators: csv.DictReader = setup_reader(csv_file, mapping_file)

    sample_pending = log_sample

    def batch_process(full_names, trunc_ids, cursor):
        nonlocal sample_pending
        results = bulk_check_for_students(full_names, trunc_ids, cursor, log_sample=sample_pending)
        sample_pending = False

        for row in results['matches']:
            logger.info(f"MATCH: {row}")
        for row in results['non_matches']:
            logger.warning(f"NO MATCH: {row}")
        return results

    # batch processing of 50 students at a time
    full_names = []
    trunc_ids = []
    matches = []
    non_matches = []
    for row in senators:
        full_names.append(normalize_case(row['full_name']))
        trunc_ids.append(get_trunc_id(row['id']))

        if len(full_names) == 50:
            res = batch_process(full_names, trunc_ids, cursor)
            matches += res['matches']
            non_matches += res['non_matches']
            full_names = []
            trunc_ids = []
    if full_names:
        res = batch_process(full_names, trunc_ids, cursor)
        matches += res['matches']
        non_matches += res['non_matches']

    return {"matches": matches, "non_matches": non_matches}


