

from argparse import ArgumentParser, Namespace
import argparse
import csv
import json
import logging
import os
from pathlib import Path
import re
import sys
import uuid

import unicodedata

logger = logging.getLogger(__name__)

def setup_logging(verbosity: int, log_file: str = "", dry_run: bool = False):
    # Add extra logging level
    addLoggingLevel('TRACE', logging.DEBUG - 5)

    level = logging.WARNING
    if verbosity == 1:
        level = logging.INFO
    elif verbosity == 2:
        level = logging.DEBUG
    elif verbosity >= 3:
        level = logging.TRACE # type: ignore

    handlers = [logging.StreamHandler(sys.stdout)]
    format_string = "%(asctime)s [%(levelname)s] %(message)s"

    if log_file:
        handlers.append(logging.FileHandler(log_file, mode='a', encoding='utf-8'))
    
    if dry_run:
        if verbosity < 3:
            level = logging.DEBUG
        format_string = "%(asctime)s [%(levelname)s] ==DRYRUN== %(message)s"

    logging.basicConfig(
        level=level,
        format=format_string,
        datefmt="%H:%M:%S",
        handlers=handlers
    )


# https://stackoverflow.com/a/35804945
def addLoggingLevel(levelName, levelNum, methodName=None):
    """
    Comprehensively adds a new logging level to the `logging` module and the
    currently configured logging class.

    `levelName` becomes an attribute of the `logging` module with the value
    `levelNum`. `methodName` becomes a convenience method for both `logging`
    itself and the class returned by `logging.getLoggerClass()` (usually just
    `logging.Logger`). If `methodName` is not specified, `levelName.lower()` is
    used.

    To avoid accidental clobberings of existing attributes, this method will
    raise an `AttributeError` if the level name is already an attribute of the
    `logging` module or if the method name is already present

    Example
    -------
    >>> addLoggingLevel('TRACE', logging.DEBUG - 5)
    >>> logging.getLogger(__name__).setLevel("TRACE")
    >>> logging.getLogger(__name__).trace('that worked')
    >>> logging.trace('so did this')
    >>> logging.TRACE
    5

    """
    if not methodName:
        methodName = levelName.lower()

    if hasattr(logging, levelName):
        raise AttributeError('{} already defined in logging module'.format(levelName))
    if hasattr(logging, methodName):
        raise AttributeError('{} already defined in logging module'.format(methodName))
    if hasattr(logging.getLoggerClass(), methodName):
        raise AttributeError('{} already defined in logger class'.format(methodName))

    # This method was inspired by the answers to Stack Overflow post
    # http://stackoverflow.com/q/2183233/2988730, especially
    # http://stackoverflow.com/a/13638084/2988730
    def logForLevel(self, message, *args, **kwargs):
        if self.isEnabledFor(levelNum):
            self._log(levelNum, message, args, **kwargs)

    def logToRoot(message, *args, **kwargs):
        logging.log(levelNum, message, *args, **kwargs)

    logging.addLevelName(levelNum, levelName)
    setattr(logging, levelName, levelNum)
    setattr(logging.getLoggerClass(), methodName, logForLevel)
    setattr(logging, methodName, logToRoot)

def load_config_from_json(path : Path):
    """
    Load a JSON configuration file from the given path.

    Parameters
    ----------
    path : Path
        The path to the JSON configuration file.

    Returns
    -------
    dict
        The loaded configuration as a dictionary. Returns an empty dictionary
        if the file does not exist.
    """
    if path:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        else:
            logger.info("No config found at path %s.", path)
    return {}

def merge_config_with_args(args: Namespace, parser: ArgumentParser):
    """
    CLI flags override config values.
    Only replace a value if the CLI used something *not equal*
    to the defaultargparse value.
    """
    conf = load_config_from_json(args.config)
   
    for key, value in vars(args).items():
        # skip config-related keys
        if key in ("config", "save_config"):
            continue
   
        # CLI overrides config if explicitly provided
        if value != parser.get_default(key):
            conf[key] = value
        else:
            # fallback to config value if exists, otherwise the default
            conf[key] = conf.get(key, value)

    return conf


def normalize_case(txt: str) -> str:
    """
    Normalize the case of a string to Title Case while erasing any extra spaces.

    Parameters
    ----------
    txt : str
        The input string to normalize.

    Returns
    -------
    str
        The normalized string.
    
    Example
    -------
    >>> normalize_case("  hello   world  ")
    'Hello World'

    >>> normalize_case("  MIXED case SEntence  ")
    'Mixed Case Sentence'

    >>> normalize_case("  eÉ  ")
    'Eé'
    """
    # Gemini Disclosure:

    # Step 1: Normalize the Unicode string (NFC ensures composed characters)
    normalized = unicodedata.normalize('NFC', txt)

    # Step 2: Define a function to capitalize the first character and lower the rest of a word
    def capitalize_match(match):
        word = match.group(0)
        # Use .capitalize() or title logic per word with proper case mapping
        # For full unicode awareness, upper/lower the first/subsequent chars:
        if not word:
            return word
        return word[0].upper() + word[1:].lower()

    # Step 3: Match Unicode word characters (supports international alphabets)
    # \w matches alphanumeric characters plus underscores in regex with re.UNICODE/default in Python 3
    return re.sub(r'\b\w+\b', capitalize_match, normalized)

def generate_uuid(base: str) -> str:
    """
    Derive a UUID (Universally Unique Identifier) as a string.

    Parameters
    ---
    base : str

    Returns
    -------
    str
        The generated UUID.
    """
    namespace = uuid.NAMESPACE_URL
    return str(uuid.uuid5(namespace, base))

def get_truncated_student_number(student_number: str) -> str:
    """
    Get the truncated student number in the format 'xxxxx####x'.

    Parameters
    ----------
    student_number : str
        The original student number.

    Returns
    -------
    str
        The truncated student number in UofT format.
    
    >>> get_truncated_student_number("1234567890")
    'xxxxx6789x'
    """
    return "xxxxx" + student_number[-5:-1] + "x"

def strip_truncated_student_number(csv_file: Path):
    """
    Strip the placeholder x characters from the truncated student number in the CSV file and save it to a temporary file.

    Parameters
    ----------
    csv_file : Path
        The path to the CSV file.

    Returns
    -------
    Path
        The path to the temporary CSV file with stripped truncated student numbers.

    >>> strip_truncated_student_number(Path("./data/fake_uoft_data.csv"))
    PosixPath('data/fake_uoft_data.stripped.csv')

    """
    temp_file = csv_file.with_suffix(".stripped.csv")
    with open(csv_file, newline='') as f_in, open(temp_file, 'w', newline='') as f_out:
        reader = csv.reader(f_in)
        headers = next(reader)

        if "Truncated Student Number" not in headers:
            raise ValueError("CSV file does not contain 'Truncated Student Number' column.")

        trunc_col_indx = headers.index("Truncated Student Number")
        writer = csv.writer(f_out)
        writer.writerow(headers)
        for row in reader:
            row[trunc_col_indx] = row[trunc_col_indx].strip("x")  # Strip the Truncated Student Number column
            writer.writerow(row)
    return temp_file


if __name__ == '__main__':
    import doctest
    doctest.testmod()
