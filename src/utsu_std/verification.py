

# Student information can be verified against the stored database records using this module

# Functions for verifying student information against the database will be implemented here.

# Example usage:
# from verification import verify_student
# result = verify_student(student_data, database)




from sqlite3 import Cursor
import logging

logger = logging.getLogger(__name__)

def check_for_student(student: dict[str, any], cursor: Cursor):
    """
    Verify the provided student information against the stored database records.

    Args:
        cursor (Cursor): The stored database records to verify against.
        student (dict[str, any]): The student object containing the student's information to be verified.

    Returns:
        bool: True if the student information matches any stored records, False otherwise.
    """

    keys = student.keys()

    # Check what student information is provided
    if not student:
        return False

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

