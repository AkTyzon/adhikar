"""Checksum validators for structured identifiers.

Regular expressions alone over-match badly: ``\\d{12}`` hits invoice numbers,
order IDs and clause numbering as readily as it hits an Aadhaar number, and a
redactor with a high false-positive rate destroys the contract text it is meant
to protect.  Every pattern in the PII catalogue that has a check digit is paired
with one of these validators, and a candidate that fails its checksum is not
treated as PII.

Each function takes the raw matched text (separators allowed) and returns whether
it is structurally valid.  None of them consult a network or a registry -- they
verify arithmetic only, so they never confirm that an identifier is *real*, just
that it is well-formed.
"""

from __future__ import annotations

import re

_NON_ALNUM = re.compile(r"[^0-9A-Za-z]")


def _digits(value: str) -> str:
    return _NON_ALNUM.sub("", value)


def luhn(value: str) -> bool:
    """Luhn mod-10 check, used by payment cards.

    >>> luhn("4539 1488 0343 6467")
    True
    >>> luhn("4539 1488 0343 6468")
    False
    """
    digits = _digits(value)
    if not digits.isdigit() or not 12 <= len(digits) <= 19:
        return False
    total = 0
    for index, char in enumerate(reversed(digits)):
        digit = int(char)
        if index % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


# Verhoeff tables (dihedral group D5). Used by the Aadhaar numbering scheme.
_D_TABLE: tuple[tuple[int, ...], ...] = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 2, 3, 4, 0, 6, 7, 8, 9, 5),
    (2, 3, 4, 0, 1, 7, 8, 9, 5, 6),
    (3, 4, 0, 1, 2, 8, 9, 5, 6, 7),
    (4, 0, 1, 2, 3, 9, 5, 6, 7, 8),
    (5, 9, 8, 7, 6, 0, 4, 3, 2, 1),
    (6, 5, 9, 8, 7, 1, 0, 4, 3, 2),
    (7, 6, 5, 9, 8, 2, 1, 0, 4, 3),
    (8, 7, 6, 5, 9, 3, 2, 1, 0, 4),
    (9, 8, 7, 6, 5, 4, 3, 2, 1, 0),
)

_P_TABLE: tuple[tuple[int, ...], ...] = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 5, 7, 6, 2, 8, 3, 0, 9, 4),
    (5, 8, 0, 3, 7, 9, 6, 1, 4, 2),
    (8, 9, 1, 6, 0, 4, 3, 5, 2, 7),
    (9, 4, 5, 3, 1, 2, 6, 8, 7, 0),
    (4, 2, 8, 6, 5, 7, 3, 9, 0, 1),
    (2, 7, 9, 3, 8, 0, 6, 4, 1, 5),
    (7, 0, 4, 6, 9, 1, 3, 2, 5, 8),
)


def verhoeff(value: str) -> bool:
    """Verhoeff check, used by Aadhaar (India's national identity number).

    An Aadhaar number is twelve digits whose last digit is a Verhoeff check
    digit, and which never begins with 0 or 1.
    """
    digits = _digits(value)
    if not digits.isdigit() or len(digits) != 12 or digits[0] in "01":
        return False
    checksum = 0
    for index, char in enumerate(reversed(digits)):
        checksum = _D_TABLE[checksum][_P_TABLE[index % 8][int(char)]]
    return checksum == 0


def pan(value: str) -> bool:
    """Indian Permanent Account Number: five letters, four digits, one letter.

    The fourth character encodes holder type and the fifth is the first letter of
    the surname, so the shape is checkable even though there is no check digit.
    """
    candidate = _digits(value).upper()
    if len(candidate) != 10:
        return False
    return (
        candidate[:5].isalpha()
        and candidate[5:9].isdigit()
        and candidate[9].isalpha()
        and candidate[3] in "ABCFGHLJPTK"
    )


def ifsc(value: str) -> bool:
    """Indian Financial System Code: four letters, a zero, then six alphanumerics."""
    candidate = _digits(value).upper()
    return len(candidate) == 11 and candidate[:4].isalpha() and candidate[4] == "0"


def mod97(value: str) -> bool:
    """ISO 7064 mod-97-10, used by IBAN."""
    candidate = _digits(value).upper()
    if not 15 <= len(candidate) <= 34 or not candidate[:2].isalpha():
        return False
    rearranged = candidate[4:] + candidate[:4]
    numeric = "".join(str(int(c, 36)) for c in rearranged)
    return int(numeric) % 97 == 1


def gstin(value: str) -> bool:
    """Indian GST identification number: 15 chars with a mod-36 check digit."""
    candidate = _digits(value).upper()
    if len(candidate) != 15:
        return False
    alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    try:
        total = 0
        for index, char in enumerate(candidate[:14]):
            product = alphabet.index(char) * (2 if index % 2 else 1)
            total += product // 36 + product % 36
    except ValueError:
        return False
    return alphabet[(36 - total % 36) % 36] == candidate[14]


def always(_: str) -> bool:
    """Accept any syntactic match. For patterns with no checkable structure."""
    return True


#: Name -> validator. The PII catalogue references validators by these names, so
#: adding a pattern never requires touching this module unless it needs new maths.
VALIDATORS: dict[str, object] = {
    "luhn": luhn,
    "verhoeff": verhoeff,
    "pan": pan,
    "ifsc": ifsc,
    "mod97": mod97,
    "gstin": gstin,
    "always": always,
}
