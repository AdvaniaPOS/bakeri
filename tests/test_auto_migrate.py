from sqlalchemy import Boolean, Column, String
from sqlalchemy.dialects.postgresql import dialect as postgresql_dialect
from sqlalchemy.dialects.sqlite import dialect as sqlite_dialect

from app.auto_migrate import _column_ddl


def test_column_ddl_quotes_string_server_default_for_postgres():
    column = Column("mfa_method", String(16), nullable=False, server_default="none")

    ddl = _column_ddl(column, postgresql_dialect())

    assert ddl == "mfa_method VARCHAR(16) NOT NULL DEFAULT 'none'"


def test_column_ddl_renders_boolean_server_default_for_postgres():
    column = Column("totp_enabled", Boolean(), nullable=False, server_default="false")

    ddl = _column_ddl(column, postgresql_dialect())

    assert ddl == "totp_enabled BOOLEAN NOT NULL DEFAULT FALSE"


def test_column_ddl_renders_boolean_server_default_for_sqlite():
    column = Column("totp_enabled", Boolean(), nullable=False, server_default="false")

    ddl = _column_ddl(column, sqlite_dialect())

    assert ddl == "totp_enabled BOOLEAN NOT NULL DEFAULT 0"