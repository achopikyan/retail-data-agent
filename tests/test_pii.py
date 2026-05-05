"""PII masking tests — column, cell, and report-text scrub paths."""
from __future__ import annotations

import pandas as pd

from src.safety.pii import EMAIL_RE, mask_dataframe, scrub_text


def test_column_named_email_is_masked():
    df = pd.DataFrame(
        {
            "user_id": [1, 2, 3],
            "email": ["alice@example.com", "bob@example.com", "carol@example.com"],
            "spend": [100.0, 200.0, 300.0],
        }
    )
    result = mask_dataframe(df)
    assert "email" in result.masked_columns
    # No '@' should remain in any masked email cell.
    for v in result.df["email"]:
        assert "@" not in v
        assert v.startswith("cust_")


def test_phone_column_is_masked():
    df = pd.DataFrame({"phone": ["+972-50-123-4567", "555-123-4567"], "x": [1, 2]})
    result = mask_dataframe(df)
    assert "phone" in result.masked_columns
    for v in result.df["phone"]:
        assert v.startswith("cust_")


def test_email_in_unrelated_string_column_is_masked():
    df = pd.DataFrame({"notes": ["please contact dave@example.com asap", "no contact info"]})
    result = mask_dataframe(df)
    # Notes column not in masked_columns, but email inside cell is gone.
    assert "@" not in result.df["notes"].iloc[0]
    assert result.cell_hits >= 1


def test_short_numeric_not_misclassified_as_phone():
    df = pd.DataFrame({"product_count": ["12345", "678"]})
    result = mask_dataframe(df)
    # Short numerics (<9 digits) should be left alone.
    assert result.df["product_count"].tolist() == ["12345", "678"]


def test_deterministic_hashing():
    df1 = pd.DataFrame({"email": ["alice@example.com"]})
    df2 = pd.DataFrame({"email": ["alice@example.com"]})
    r1 = mask_dataframe(df1)
    r2 = mask_dataframe(df2)
    assert r1.df["email"].iloc[0] == r2.df["email"].iloc[0]


def test_scrub_text_catches_leakage():
    leaky = "Top customer is alice@example.com, phone +972-50-123-4567."
    cleaned, hits = scrub_text(leaky)
    assert hits >= 2
    assert "alice@example.com" not in cleaned
    assert "+972-50-123-4567" not in cleaned


def test_scrub_text_no_false_positive_on_clean():
    clean = "Top customer cust_a3f1b2c9 spent $4,500 this quarter."
    out, hits = scrub_text(clean)
    assert hits == 0
    assert out == clean


def test_email_regex_basic():
    # Quick sanity check on the regex itself.
    assert EMAIL_RE.search("a@b.co") is not None
    assert EMAIL_RE.search("not-an-email") is None
