"""IOC-02 CSV parser unit tests. Implemented by Plan 22-05 Task 1."""
import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("SECRET_KEY", "s" * 64)
os.environ.setdefault("JWT_SIGNING_KEY", "j" * 64)


def test_csv_parses_minimum_type_value_columns():
    from app.services.ioc_import.csv_parser import parse_csv_rows
    rows = list(parse_csv_rows(b"type,value\nip,1.2.3.4\n"))
    assert len(rows) == 1 and rows[0].type == "ip" and rows[0].value == "1.2.3.4"


def test_csv_accepts_vendor_indicator_type_shape():
    from app.services.ioc_import.csv_parser import parse_csv_rows
    rows = list(parse_csv_rows(b"indicator,type\n1.2.3.4,ip\n"))
    assert len(rows) == 1 and rows[0].type == "ip" and rows[0].value == "1.2.3.4"


def test_csv_collects_per_row_errors_with_line_numbers():
    from app.services.ioc_import.csv_parser import parse_csv_rows
    rows = list(parse_csv_rows(b"type,value\nbogus,zzz\n"))
    assert any(getattr(r, "error", None) and getattr(r, "line", None) == 2 for r in rows)


def test_csv_parses_project_id_and_source_columns():
    """CONTEXT.md §CSV columns - project_id 'global' → None; source carried through."""
    from app.services.ioc_import.csv_parser import parse_csv_rows
    rows = list(parse_csv_rows(b"type,value,project_id,source\nip,1.2.3.4,global,csv\n"))
    assert len(rows) == 1
    r = rows[0]
    assert r.error is None
    assert r.project_id is None
    assert r.source == "csv"
