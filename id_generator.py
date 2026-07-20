import random
import string


def generate_employee_id(department_code: str) -> str:
    """
    Generates an employee ID like 'MAT-7X3K91':
    department code, dash, 6 random uppercase letters/digits.

    Collision checking (making sure this ID doesn't already exist)
    happens in the route that calls this, since that's where we
    have access to the database session.
    """
    random_part = "".join(
        random.choices(string.ascii_uppercase + string.digits, k=6)
    )
    return f"{department_code}-{random_part}"
