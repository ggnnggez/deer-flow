"""SQL storage tests for the Phase 10 evaluation projections."""

from __future__ import annotations

from pathlib import Path

from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from deerflow.ansich.persistence.models import (
    AnsichEvaluationIndexRow,
    AnsichReleaseQualityStatsRow,
)

EVALUATION_REVISION = "0023_ansich_evaluations"
PREVIOUS_REVISION = "0022_ansich_assessor_deadline"
EVALUATION_TABLES = {"ansich_evaluation_index", "ansich_release_quality_stats"}


def _alembic_config(database_path: Path) -> AlembicConfig:
    backend_root = Path(__file__).resolve().parents[2]
    config = AlembicConfig(str(backend_root / "packages" / "harness" / "deerflow" / "persistence" / "migrations" / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database_path}")
    # The Alembic env only applies process-wide logging.fileConfig when this
    # remains set; the integration test must not disable loggers used later.
    config.config_file_name = None
    return config


def _sqlite_schema(database_path: Path) -> tuple[set[str], dict[str, set[str]], dict[str, set[str]], str]:
    engine = create_engine(f"sqlite:///{database_path}")
    try:
        database_inspector = inspect(engine)
        table_names = set(database_inspector.get_table_names())
        columns = {table: {column["name"] for column in database_inspector.get_columns(table)} for table in EVALUATION_TABLES & table_names}
        indexes = {table: {index["name"] for index in database_inspector.get_indexes(table)} for table in EVALUATION_TABLES & table_names}
        with engine.connect() as connection:
            revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
    finally:
        engine.dispose()
    return table_names, columns, indexes, revision


def test_evaluation_models_compile_with_postgresql_constraints_and_indexes() -> None:
    dialect = postgresql.dialect()
    ddl = {model.__tablename__: str(CreateTable(model.__table__).compile(dialect=dialect)) for model in (AnsichEvaluationIndexRow, AnsichReleaseQualityStatsRow)}

    assert "PRIMARY KEY (evaluation_obs_id)" in ddl["ansich_evaluation_index"]
    assert "FOREIGN KEY(evaluation_obs_id) REFERENCES ansich_observations (obs_id) ON DELETE CASCADE" in ddl["ansich_evaluation_index"]
    assert "score FLOAT" in ddl["ansich_evaluation_index"]
    assert "scale_higher_is_better BOOLEAN" in ddl["ansich_evaluation_index"]
    assert "occurred_at TIMESTAMP WITH TIME ZONE NOT NULL" in ddl["ansich_evaluation_index"]

    assert "PRIMARY KEY (release_id, cohort_key, dimension)" in ddl["ansich_release_quality_stats"]
    assert "FOREIGN KEY(release_id) REFERENCES ansich_entities (entity_id) ON DELETE CASCADE" in ddl["ansich_release_quality_stats"]
    assert "assessed_count INTEGER NOT NULL" in ddl["ansich_release_quality_stats"]
    assert "score_sum FLOAT" in ddl["ansich_release_quality_stats"]
    assert "as_of TIMESTAMP WITH TIME ZONE NOT NULL" in ddl["ansich_release_quality_stats"]

    assert {index.name for index in AnsichEvaluationIndexRow.__table__.indexes} == {
        "ix_ansich_evaluation_subject_dimension",
        "ix_ansich_evaluation_suite_case",
        "ix_ansich_evaluation_task",
    }
    assert {index.name for index in AnsichReleaseQualityStatsRow.__table__.indexes} == {"ix_ansich_release_quality_cohort"}


def test_evaluation_migration_upgrades_sqlite(tmp_path) -> None:
    database_path = tmp_path / "ansich-evaluations-migration.db"
    config = _alembic_config(database_path)

    alembic_command.upgrade(config, "head")

    table_names, columns, indexes, revision = _sqlite_schema(database_path)

    assert EVALUATION_TABLES <= table_names
    assert columns["ansich_evaluation_index"] == {column.name for column in AnsichEvaluationIndexRow.__table__.columns}
    assert columns["ansich_release_quality_stats"] == {column.name for column in AnsichReleaseQualityStatsRow.__table__.columns}
    assert indexes["ansich_evaluation_index"] == {index.name for index in AnsichEvaluationIndexRow.__table__.indexes}
    assert indexes["ansich_release_quality_stats"] == {index.name for index in AnsichReleaseQualityStatsRow.__table__.indexes}
    assert revision == EVALUATION_REVISION
    assert len(revision) <= 32


def test_evaluation_migration_is_idempotent_on_existing_tables(tmp_path) -> None:
    """A legacy ``create_all`` database that already carries the tables still upgrades."""

    database_path = tmp_path / "ansich-evaluations-existing.db"
    config = _alembic_config(database_path)
    alembic_command.upgrade(config, PREVIOUS_REVISION)

    engine = create_engine(f"sqlite:///{database_path}")
    try:
        AnsichEvaluationIndexRow.__table__.create(engine)
        AnsichReleaseQualityStatsRow.__table__.create(engine)
    finally:
        engine.dispose()

    alembic_command.upgrade(config, "head")

    table_names, columns, indexes, revision = _sqlite_schema(database_path)

    assert EVALUATION_TABLES <= table_names
    assert columns["ansich_evaluation_index"] == {column.name for column in AnsichEvaluationIndexRow.__table__.columns}
    assert indexes["ansich_release_quality_stats"] == {index.name for index in AnsichReleaseQualityStatsRow.__table__.indexes}
    assert revision == EVALUATION_REVISION


def test_evaluation_migration_downgrade_drops_tables(tmp_path) -> None:
    database_path = tmp_path / "ansich-evaluations-downgrade.db"
    config = _alembic_config(database_path)
    alembic_command.upgrade(config, "head")

    alembic_command.downgrade(config, PREVIOUS_REVISION)

    table_names, _columns, _indexes, revision = _sqlite_schema(database_path)

    assert not (EVALUATION_TABLES & table_names)
    assert revision == PREVIOUS_REVISION
