from sqlalchemy.dialects import mysql, sqlite

from app.database.models import Message


def test_message_timestamp_preserves_mysql_microseconds_and_sqlite_tests():
    column_type = Message.__table__.c.created_at.type
    assert column_type.compile(dialect=mysql.dialect()) == "DATETIME(6)"
    assert column_type.compile(dialect=sqlite.dialect()) == "DATETIME"
