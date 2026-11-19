"""Strict scalar grammar shared by all user-downloadable CSVs."""
from datetime import datetime
from decimal import Decimal
from math import isfinite, isnan
from numbers import Integral, Real
import re

import pandas as pd

_MONTH = re.compile(r'[0-9]{4}-(?:0[1-9]|1[0-2])\Z')
_STAMP = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?(?:Z|[+-][0-9]{2}:[0-9]{2})\Z')


def csv_cell(value) -> str:
    if value is None or value is pd.NA or value is pd.NaT:
        return ''
    if isinstance(value, bool):
        raise ValueError('CSV cell must not be boolean')
    if isinstance(value, (Real, Decimal)):
        if isnan(value):return ''
        if not isfinite(value):raise ValueError('CSV cell must be finite')
        return str(int(value)) if isinstance(value, Integral) else format(float(value), '.17g')
    if isinstance(value, datetime):
        value = value.isoformat()
    if isinstance(value, str):
        if _MONTH.fullmatch(value) and int(value[:4])>0:return value
        if _STAMP.fullmatch(value):
            try:
                parsed = datetime.fromisoformat(value)
                if parsed.utcoffset() is not None:return value
            except ValueError:pass
    raise ValueError('CSV cell is outside the strict numeric/timestamp/month grammar')
