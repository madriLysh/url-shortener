import pytest
from utils.base62 import Base62
from string import punctuation

CASES = [
    ("0", 0),
    ("9", 9),
    ("a", 10),
    ("z", 35),
    ("A", 36),
    ("Z", 61),
    ("10", 62),
    ("ZZ", 3843),
    ("100", 3844),
    ("4c91", 999999),
    ("8m0Kx", 123456789),
    ("aZl8N0y58M7", 2**63 - 1),
    ("hBxM5A4", 10**12)
]
@pytest.mark.parametrize("string, number", CASES)

def test_encoded(string, number):
    assert Base62.encode(number) == string

@pytest.mark.parametrize("string, number", CASES)
def test_decode(string, number):
    assert Base62.decode(string) == number

@pytest.mark.parametrize("char", punctuation)
def test_decode_reject_invalid(char):
    with pytest.raises(ValueError):
        Base62.decode(char)

def test_negative_number_encode():
    with pytest.raises(ValueError):
        Base62.encode(-1)

def test_roundtrip():
    for n in range(0, 1_000_000, 997):
        assert Base62.decode(Base62.encode(n)) == n

