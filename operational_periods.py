"""Explicit target quarters shared by the operational CLIs."""
import re
from datetime import date


def target_quarter(value=None, today=None):
    if value:
        if not re.fullmatch(r"20\d{2}T[1-4]", value):
            raise ValueError("periodo-alvo deve usar AAAATn, por exemplo 2026T2")
        return value
    today = today or date.today()
    quarter = (today.month - 1) // 3
    return f"{today.year if quarter else today.year - 1}T{quarter or 4}"


def display_quarter(value):
    value = target_quarter(value)
    return f"{value[-1]}T{value[2:4]}"
