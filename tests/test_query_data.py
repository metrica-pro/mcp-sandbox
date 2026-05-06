"""Unit tests for query_data tool — direct _query_sync calls, no server."""

from __future__ import annotations

import pytest

from main import (
    MAX_DATA_LENGTH,
    MAX_SQL_LENGTH,
    _detect_format,
    _parse_csv_data,
    _parse_json_data,
    _query_data_validate,
    _query_sync,
)


class TestDetectFormat:
    def test_detect_json_array(self) -> None:
        assert _detect_format('[{"a":1}]') == "json"

    def test_detect_json_object(self) -> None:
        assert _detect_format('{"a":1}') == "json"

    def test_detect_csv(self) -> None:
        assert _detect_format("name,age\nAlice,30") == "csv"

    def test_detect_with_leading_whitespace(self) -> None:
        assert _detect_format('  {"a":1}') == "json"
        assert _detect_format("  name,age\nA,1") == "csv"


class TestQueryDataValidate:
    def test_empty_sql(self) -> None:
        result = _query_data_validate("", None, "auto")
        assert result is not None
        assert "must not be empty" in result["error"]

    def test_whitespace_sql(self) -> None:
        result = _query_data_validate("   ", None, "auto")
        assert result is not None
        assert "must not be empty" in result["error"]

    def test_sql_too_large(self) -> None:
        big_sql = "SELECT " + "x" * MAX_SQL_LENGTH
        result = _query_data_validate(big_sql, None, "auto")
        assert result is not None
        assert "exceeds maximum size" in result["error"]

    def test_non_select_sql_insert(self) -> None:
        result = _query_data_validate("INSERT INTO t VALUES (1)", None, "auto")
        assert result is not None
        assert "Only SELECT" in result["error"]

    def test_non_select_sql_drop(self) -> None:
        result = _query_data_validate("DROP TABLE t", None, "auto")
        assert result is not None
        assert "Only SELECT" in result["error"]

    def test_non_select_sql_create(self) -> None:
        result = _query_data_validate("CREATE TABLE t (a int)", None, "auto")
        assert result is not None
        assert "Only SELECT" in result["error"]

    def test_non_select_sql_attach(self) -> None:
        result = _query_data_validate("ATTACH 'db' AS other", None, "auto")
        assert result is not None
        assert "Only SELECT" in result["error"]

    def test_invalid_data_format(self) -> None:
        result = _query_data_validate("SELECT 1", None, "xml")
        assert result is not None
        assert "data_format" in result["error"]

    def test_empty_data_with_data_param(self) -> None:
        result = _query_data_validate("SELECT 1", "", "auto")
        assert result is not None
        assert "must not be empty" in result["error"]

    def test_data_too_large(self) -> None:
        big_data = "x" * (MAX_DATA_LENGTH + 1)
        result = _query_data_validate("SELECT 1", big_data, "auto")
        assert result is not None
        assert "exceeds maximum size" in result["error"]

    def test_valid_sql_no_data(self) -> None:
        result = _query_data_validate("SELECT 1", None, "auto")
        assert result is None

    def test_valid_sql_with_data(self) -> None:
        result = _query_data_validate("SELECT * FROM input_data", "a\n1", "csv")
        assert result is None


class TestParseCSV:
    def test_simple_csv(self) -> None:
        columns, rows = _parse_csv_data("name,age\nAlice,30\nBob,25")
        assert columns == ["name", "age"]
        assert rows == [("Alice", "30"), ("Bob", "25")]

    def test_csv_tab_separated(self) -> None:
        columns, rows = _parse_csv_data("name\tage\nAlice\t30")
        assert columns == ["name", "age"]
        assert rows == [("Alice", "30")]

    def test_csv_semicolon_separated(self) -> None:
        columns, rows = _parse_csv_data("name;age\nAlice;30")
        assert columns == ["name", "age"]
        assert rows == [("Alice", "30")]

    def test_csv_header_only(self) -> None:
        columns, rows = _parse_csv_data("name,age")
        assert columns == ["name", "age"]
        assert rows == []


class TestParseJSON:
    def test_array_of_objects(self) -> None:
        columns, rows = _parse_json_data('[{"a":1,"b":2},{"a":3,"b":4}]')
        assert columns == ["a", "b"]
        assert rows == [(1, 2), (3, 4)]

    def test_single_object(self) -> None:
        columns, rows = _parse_json_data('{"name":"Alice","age":30}')
        assert columns == ["name", "age"]
        assert rows == [("Alice", 30)]

    def test_invalid_json_syntax(self) -> None:
        with pytest.raises(ValueError):
            _parse_json_data("{not json}")

    def test_missing_keys_filled_with_none(self) -> None:
        columns, rows = _parse_json_data('[{"a":1},{"b":2}]')
        assert columns == ["a", "b"]
        assert rows == [(1, None), (None, 2)]


class TestQuerySync:
    def test_csv_auto_format(self) -> None:
        result = _query_sync(
            "SELECT * FROM input_data",
            "name,age\nAlice,30\nBob,25",
            "auto",
        )
        assert "error" not in result
        assert result["columns"] == ["name", "age"]
        assert result["row_count"] == 2
        assert {"name": "Alice", "age": "30"} in result["rows"]

    def test_json_array_of_objects(self) -> None:
        result = _query_sync(
            "SELECT * FROM input_data",
            '[{"x":1},{"x":2}]',
            "auto",
        )
        assert "error" not in result
        assert result["row_count"] == 2

    def test_json_single_object(self) -> None:
        result = _query_sync(
            "SELECT * FROM input_data",
            '{"a":1}',
            "auto",
        )
        assert "error" not in result
        assert result["row_count"] == 1

    def test_no_data_pure_select(self) -> None:
        result = _query_sync("SELECT 1+1 AS result", None, "auto")
        assert "error" not in result
        assert result["columns"] == ["result"]
        assert result["rows"] == [{"result": 2}]
        assert result["row_count"] == 1

    def test_aggregation(self) -> None:
        result = _query_sync(
            "SELECT AVG(CAST(age AS DOUBLE)) as avg_age FROM input_data",
            "name,age\nAlice,30\nBob,25\nCharlie,35",
            "csv",
        )
        assert "error" not in result
        assert result["row_count"] == 1
        assert result["rows"][0]["avg_age"] == 30.0

    def test_join(self) -> None:
        data = "id,name\n1,Alice\n2,Bob"
        result = _query_sync(
            "SELECT a.name as n1, b.name as n2 FROM input_data a JOIN input_data b ON a.id=b.id",
            data,
            "csv",
        )
        assert "error" not in result
        assert result["row_count"] == 2

    def test_sql_syntax_error(self) -> None:
        result = _query_sync("SELECT * FROM", None, "auto")
        assert "error" in result

    def test_missing_table(self) -> None:
        result = _query_sync("SELECT * FROM nonexistent", None, "auto")
        assert "error" in result

    def test_read_csv_auto_blocked(self) -> None:
        result = _query_sync(
            "SELECT * FROM read_csv_auto('/etc/passwd')",
            None,
            "auto",
        )
        assert "error" in result

    def test_query_timeout(self) -> None:
        result = _query_sync(
            "WITH RECURSIVE t AS (SELECT 1 UNION ALL SELECT * FROM t) SELECT * FROM t",
            None,
            "auto",
        )
        assert "error" in result
        assert "timeout" in result["error"].lower()

    def test_empty_data_error(self) -> None:
        result = _query_sync("SELECT 1", "", "auto")
        assert "error" in result
        assert "must not be empty" in result["error"]

    def test_invalid_json_error(self) -> None:
        result = _query_sync("SELECT 1", "{not valid}", "json")
        assert "error" in result
        assert "Failed to parse" in result["error"]

    def test_invalid_data_format_error(self) -> None:
        result = _query_sync("SELECT 1", "a\n1", "xml")
        assert "error" in result
