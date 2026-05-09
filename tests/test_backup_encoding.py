from datetime import date, datetime, timezone
from decimal import Decimal

from app.backup import decode_value, encode_value


def test_int_roundtrip():
    assert encode_value(42) == 42
    assert decode_value(42) == 42


def test_string_roundtrip():
    assert encode_value("hello") == "hello"
    assert decode_value("hello") == "hello"


def test_none_roundtrip():
    assert encode_value(None) is None
    assert decode_value(None) is None


def test_bool_roundtrip():
    assert encode_value(True) is True
    assert decode_value(False) is False


def test_decimal_preserves_trailing_zeros():
    assert encode_value(Decimal("12.50")) == "12.50"
    decoded = decode_value("12.50", target_type=Decimal)
    assert decoded == Decimal("12.50")
    assert str(decoded) == "12.50"


def test_decimal_zero():
    assert encode_value(Decimal("0.00")) == "0.00"
    assert decode_value("0.00", target_type=Decimal) == Decimal("0.00")


def test_datetime_roundtrip():
    dt = datetime(2026, 5, 9, 14, 30, 15, tzinfo=timezone.utc)
    encoded = encode_value(dt)
    assert encoded == "2026-05-09T14:30:15+00:00"
    decoded = decode_value(encoded, target_type=datetime)
    assert decoded == dt


def test_naive_datetime_roundtrip():
    dt = datetime(2026, 5, 9, 14, 30, 15)
    encoded = encode_value(dt)
    decoded = decode_value(encoded, target_type=datetime)
    assert decoded == dt


def test_date_roundtrip():
    d = date(2026, 5, 9)
    assert encode_value(d) == "2026-05-09"
    assert decode_value("2026-05-09", target_type=date) == d


def test_bytes_roundtrip():
    payload = b"\x00\x01\x02hello"
    encoded = encode_value(payload)
    assert encoded == {"__b64__": "AAECaGVsbG8="}
    assert decode_value(encoded, target_type=bytes) == payload
