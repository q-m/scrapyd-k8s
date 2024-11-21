from datetime import datetime
import pytest
from scrapyd_k8s.utils import format_datetime_object, format_iso_date_string


def test_format_iso_date_string():
    input_date = "2024-08-30T13:45:30.123456"
    expected = "2024-08-30 13:45:30.123456"
    assert format_iso_date_string(input_date) == expected

def test_format_iso_date_string_invalid():
    with pytest.raises(ValueError):
        format_iso_date_string("invalid_date")

def test_format_datetime_object():
    input_datetime = datetime(2024, 8, 30, 13, 45, 30, 123456)
    expected = "2024-08-30 13:45:30.123456"
    assert format_datetime_object(input_datetime) == expected
