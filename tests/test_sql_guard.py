"""SQL guard tests — verify SELECT-only and dataset whitelist."""
from __future__ import annotations

from src.safety.sql_guard import validate_sql


GOOD = "SELECT COUNT(*) FROM `bigquery-public-data.thelook_ecommerce.orders`"


def test_simple_select_passes():
    assert validate_sql(GOOD).ok


def test_with_cte_passes():
    sql = (
        "WITH t AS (SELECT 1 FROM `bigquery-public-data.thelook_ecommerce.orders`) "
        "SELECT * FROM t"
    )
    assert validate_sql(sql).ok


def test_delete_blocked():
    sql = "DELETE FROM `bigquery-public-data.thelook_ecommerce.orders`"
    r = validate_sql(sql)
    assert not r.ok


def test_insert_blocked():
    sql = "INSERT INTO `bigquery-public-data.thelook_ecommerce.orders` VALUES (1)"
    assert not validate_sql(sql).ok


def test_drop_blocked():
    sql = "SELECT 1; DROP TABLE x"
    assert not validate_sql(sql).ok


def test_other_dataset_blocked():
    sql = "SELECT * FROM `bigquery-public-data.austin_311.311_request`"
    assert not validate_sql(sql).ok


def test_empty_blocked():
    assert not validate_sql("").ok
    assert not validate_sql("   ").ok
