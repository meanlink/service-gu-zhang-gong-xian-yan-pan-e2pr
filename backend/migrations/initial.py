from sqlalchemy import inspect, text
from src.config.database import Base, engine
from src import models


ADDITIVE_COLUMNS = {
    'jobs': [
        ('calibration_scheme_id', 'INTEGER'),
        ('calibration_revision', 'INTEGER'),
        ('calibration_snapshot', 'JSON'),
        ('invalidated', 'BOOLEAN DEFAULT FALSE'),
        ('invalidation_reason', "VARCHAR(500) DEFAULT ''"),
        ('invalidated_at', 'DOUBLE PRECISION'),
    ],
    'reports': [
        ('basis_revoked', 'BOOLEAN DEFAULT FALSE'),
        ('basis_revoked_at', 'DOUBLE PRECISION'),
        ('revocation_note', "VARCHAR(500) DEFAULT ''"),
    ],
    'deliveries': [
        ('calibration_scheme_id', 'INTEGER'),
        ('calibration_revision', 'INTEGER'),
        ('basis_revoked', 'BOOLEAN DEFAULT FALSE'),
        ('basis_revoked_at', 'DOUBLE PRECISION'),
        ('revocation_note', "VARCHAR(500) DEFAULT ''"),
    ],
}


def migrate():
    Base.metadata.create_all(engine)
    inspector = inspect(engine)
    dialect = engine.dialect.name
    with engine.begin() as conn:
        for table, columns in ADDITIVE_COLUMNS.items():
            existing = {c['name'] for c in inspector.get_columns(table)}
            for name, sql_type in columns:
                if name in existing:
                    continue
                if dialect == 'sqlite':
                    sql_type = sql_type.replace('DOUBLE PRECISION', 'FLOAT')
                conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {name} {sql_type}'))


if __name__ == '__main__':
    migrate()
