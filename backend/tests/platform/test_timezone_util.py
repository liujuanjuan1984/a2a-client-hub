from datetime import date

from app.utils.timezone_util import get_day_window


def test_day_window_duration_minutes_regular_day():
    window = get_day_window("UTC", date(2024, 1, 15))
    assert window.duration_minutes == 24 * 60


def test_day_window_duration_minutes_dst_spring_forward():
    window = get_day_window("America/New_York", date(2024, 3, 10))
    assert window.duration_minutes == 23 * 60


def test_day_window_duration_minutes_dst_fall_back():
    window = get_day_window("America/New_York", date(2024, 11, 3))
    assert window.duration_minutes == 25 * 60
