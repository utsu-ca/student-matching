

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
from turtledemo.penrose import draw

import unicodedata

logger = logging.getLogger(__name__)

def setup_logging(args):
    # Add extra logging level
    addLoggingLevel('TRACE', logging.DEBUG - 5)

    verbosity = args['verbosity']
    log_file = args['log_file']
    dry_run = args['dry_run']


    level = logging.WARNING
    if verbosity == 'INFO':
        level = logging.INFO
    elif verbosity == 'DEBUG':
        level = logging.DEBUG
    elif verbosity >= 'TRACE':
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


def save_config_file(path: str, cfg):
    """Save JSON config."""
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        logger.info(f"Saved configuration to {path}")
    except Exception as e:
        logger.error(f"Failed to save config to {path}: {e}")


def load_config_file(path: str) -> dict[any, any]: # type: ignore
    """Load JSON. Return an object/dict."""
    if not path:
        return {}
    try:
        p = Path(path)
        if not p.exists():
            logger.error(f"Config file not found: {path}")
            return {}
        with p.open("r", encoding="utf-8") as f:
            raw = f.read()
            cfg = json.loads(raw)
            logger.info(f"Loaded config: {path}")
            return dict(cfg)
    except Exception as e:
        logger.error(f"Failed to load config file {path}: {e}")
        return {}


def load_and_merge_config(args: Namespace, parser: ArgumentParser):
    """
    CLI flags override config values.
    Only replace a value if the CLI used something *not equal*
    to the defaultargparse value.
    """
    conf = load_config_file(args.config)

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

    save_config_file(args.config, conf)

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
    capitalized = re.sub(r'\b\w+\b', capitalize_match, normalized)

    # Step 4: Collapse runs of whitespace into a single space and trim the ends
    return re.sub(r'\s+', ' ', capitalized).strip()

def normalize_name(first_name: str, last_name: str) -> str:
    """
    Normalize the full name by normalizing the first and last names and combining them.

    Parameters
    ----------
    first_name : str
        The first name of the person.
    last_name : str
        The last name of the person.

    Returns
    -------
    str
        The normalized full name in the format "First Last".

    Example
    -------
    >>> normalize_name("  john  ", "  doe  ")
    'John Doe'
    """
    return f"{normalize_case(first_name)} {normalize_case(last_name)}"

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

def get_uoft_trunc_format(student_number: str) -> str:
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
    
    >>> get_uoft_trunc_format("1234567890")
    'xxxxx6789x'
    """
    return "xxxxx" + student_number[-5:-1] + "x"

def get_trunc_id(id_txt: str):
    # sanity strip
    id_txt.strip()
    if len(id_txt) == 4:
        # string is likely already in the correct format
        return id_txt

    if id_txt[-1] == "x":
        # str likely needs to be stripped
        return id_txt.strip("x")

    if len(id_txt) > 8:
        trunc = id_txt[-5:-1]
        return trunc

def strip_uoft_trunc_placeholders(csv_file: Path):
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

def resolve_project_root():
    # Get the directory of the currently executing script
    current_dir = Path(__file__).resolve().parent

    # Traverse upward until you find a folder containing 'src'
    project_root = current_dir
    while project_root != project_root.parent:
        if (project_root / "src").is_dir():
            return project_root
        project_root = project_root.parent
    else:
        print("src folder not found in parent directories.")
    return None

def absfile(relative_path: str) -> Path:
    """
    Return the absolute path to a file relative to the project root.

    Parameters
    ----------
    relative_path : str
        The relative path to the file from the project root.

    Returns
    -------
    Path | None
        The absolute path to the file if the project root is found, otherwise None.
    """
    project_root = resolve_project_root()
    if project_root is None:
        return Path(relative_path)
    return project_root / relative_path


if __name__ == '__main__':
    import doctest
    doctest.testmod()
