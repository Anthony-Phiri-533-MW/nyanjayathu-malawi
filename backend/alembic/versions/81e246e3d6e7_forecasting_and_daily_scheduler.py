"""forecasting and daily scheduler

Revision ID: 81e246e3d6e7
Revises: 768aa9874ed3
Create Date: 2026-11-05 11:34:46.087212

Adds the MODELS / EVALUATIONS / FORECAST_RUNS / SCHEDULER_RUNS entities from the
project ER diagram plus the schedule columns on DATA_SOURCES and the model
provenance columns on FORECASTS.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
import app.models.base  # noqa: F401  (GeoJSONType used below resolves via this import)


revision = '81e246e3d6e7'
down_revision = '768aa9874ed3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'models',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('key', sa.String(length=200), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('algorithm', sa.String(length=60), nullable=False),
        sa.Column('version', sa.String(length=40), nullable=False),
        sa.Column('indicator_key', sa.String(length=80), nullable=False),
        sa.Column('study_area_id', sa.Integer(), nullable=True),
        sa.Column('cadence', sa.String(length=20), nullable=False),
        sa.Column('n_lags', sa.Integer(), nullable=False),
        sa.Column('feature_names_json', app.models.base.GeoJSONType(), nullable=True),
        sa.Column('params_json', app.models.base.GeoJSONType(), nullable=True),
        sa.Column('train_start', sa.Date(), nullable=True),
        sa.Column('train_end', sa.Date(), nullable=True),
        sa.Column('n_train', sa.Integer(), nullable=False),
        sa.Column('metrics_json', app.models.base.GeoJSONType(), nullable=True),
        sa.Column('rmse', sa.Float(), nullable=True),
        sa.Column('mae', sa.Float(), nullable=True),
        sa.Column('bias', sa.Float(), nullable=True),
        sa.Column('skill_score', sa.Float(), nullable=True),
        sa.Column('artifact_path', sa.String(length=500), nullable=True),
        sa.Column('artifact_sha256', sa.String(length=64), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('trained_at', sa.DateTime(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['study_area_id'], ['study_areas.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('key'),
    )
    with op.batch_alter_table('models', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_models_algorithm'), ['algorithm'], unique=False)
        batch_op.create_index(batch_op.f('ix_models_indicator_key'), ['indicator_key'], unique=False)
        batch_op.create_index(batch_op.f('ix_models_is_active'), ['is_active'], unique=False)
        batch_op.create_index(batch_op.f('ix_models_key'), ['key'], unique=True)
        batch_op.create_index(batch_op.f('ix_models_study_area_id'), ['study_area_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_models_trained_at'), ['trained_at'], unique=False)

    op.create_table(
        'forecast_runs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('study_area_id', sa.Integer(), nullable=False),
        sa.Column('indicator_key', sa.String(length=80), nullable=False),
        sa.Column('model_id', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('horizon_days', sa.Integer(), nullable=False),
        sa.Column('issued_at', sa.DateTime(), nullable=False),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.Column('row_count', sa.Integer(), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('metrics_json', app.models.base.GeoJSONType(), nullable=True),
        sa.ForeignKeyConstraint(['model_id'], ['models.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['study_area_id'], ['study_areas.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('forecast_runs', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_forecast_runs_indicator_key'), ['indicator_key'], unique=False)
        batch_op.create_index(batch_op.f('ix_forecast_runs_issued_at'), ['issued_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_forecast_runs_model_id'), ['model_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_forecast_runs_status'), ['status'], unique=False)
        batch_op.create_index(batch_op.f('ix_forecast_runs_study_area_id'), ['study_area_id'], unique=False)

    op.create_table(
        'evaluations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('model_id', sa.Integer(), nullable=False),
        sa.Column('indicator_key', sa.String(length=80), nullable=False),
        sa.Column('study_area_id', sa.Integer(), nullable=True),
        sa.Column('fold', sa.Integer(), nullable=False),
        sa.Column('horizon_days', sa.Integer(), nullable=False),
        sa.Column('train_start', sa.Date(), nullable=True),
        sa.Column('train_end', sa.Date(), nullable=True),
        sa.Column('test_start', sa.Date(), nullable=True),
        sa.Column('test_end', sa.Date(), nullable=True),
        sa.Column('n_train', sa.Integer(), nullable=False),
        sa.Column('n_test', sa.Integer(), nullable=False),
        sa.Column('rmse', sa.Float(), nullable=True),
        sa.Column('mae', sa.Float(), nullable=True),
        sa.Column('bias', sa.Float(), nullable=True),
        sa.Column('mape', sa.Float(), nullable=True),
        sa.Column('r2', sa.Float(), nullable=True),
        sa.Column('skill_score', sa.Float(), nullable=True),
        sa.Column('coverage', sa.Float(), nullable=True),
        sa.Column('metrics_json', app.models.base.GeoJSONType(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['model_id'], ['models.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('evaluations', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_evaluations_indicator_key'), ['indicator_key'], unique=False)
        batch_op.create_index(batch_op.f('ix_evaluations_model_id'), ['model_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_evaluations_study_area_id'), ['study_area_id'], unique=False)

    op.create_table(
        'scheduler_runs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('run_date', sa.Date(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('trigger', sa.String(length=20), nullable=False),
        sa.Column('job_id', sa.Integer(), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=False),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.Column('summary_json', app.models.base.GeoJSONType(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('scheduler_runs', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_scheduler_runs_job_id'), ['job_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_scheduler_runs_run_date'), ['run_date'], unique=True)
        batch_op.create_index(batch_op.f('ix_scheduler_runs_started_at'), ['started_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_scheduler_runs_status'), ['status'], unique=False)

    with op.batch_alter_table('data_sources', schema=None) as batch_op:
        batch_op.add_column(sa.Column('schedule_enabled', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column('schedule_time_utc', sa.String(length=5), nullable=False, server_default='02:00'))
        batch_op.add_column(sa.Column('schedule_lookback_days', sa.Integer(), nullable=False, server_default='3'))
        batch_op.add_column(sa.Column('last_scheduled_at', sa.DateTime(), nullable=True))
        batch_op.create_index(batch_op.f('ix_data_sources_schedule_enabled'), ['schedule_enabled'], unique=False)

    with op.batch_alter_table('forecast_values', schema=None) as batch_op:
        batch_op.add_column(sa.Column('source', sa.String(length=10), nullable=False, server_default='manual'))
        batch_op.add_column(sa.Column('model_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('run_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('lead_time_days', sa.Integer(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('lower', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('upper', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('issued_at', sa.DateTime(), nullable=True))
        batch_op.create_index(batch_op.f('ix_forecast_values_model_id'), ['model_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_forecast_values_run_id'), ['run_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_forecast_values_source'), ['source'], unique=False)
        batch_op.create_foreign_key(
            batch_op.f('fk_forecast_values_model_id_models'), 'models', ['model_id'], ['id'], ondelete='SET NULL'
        )
        batch_op.create_foreign_key(
            batch_op.f('fk_forecast_values_run_id_forecast_runs'), 'forecast_runs', ['run_id'], ['id'], ondelete='SET NULL'
        )


def downgrade() -> None:
    with op.batch_alter_table('forecast_values', schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f('fk_forecast_values_run_id_forecast_runs'), type_='foreignkey')
        batch_op.drop_constraint(batch_op.f('fk_forecast_values_model_id_models'), type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_forecast_values_source'))
        batch_op.drop_index(batch_op.f('ix_forecast_values_run_id'))
        batch_op.drop_index(batch_op.f('ix_forecast_values_model_id'))
        batch_op.drop_column('issued_at')
        batch_op.drop_column('upper')
        batch_op.drop_column('lower')
        batch_op.drop_column('lead_time_days')
        batch_op.drop_column('run_id')
        batch_op.drop_column('model_id')
        batch_op.drop_column('source')

    with op.batch_alter_table('data_sources', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_data_sources_schedule_enabled'))
        batch_op.drop_column('last_scheduled_at')
        batch_op.drop_column('schedule_lookback_days')
        batch_op.drop_column('schedule_time_utc')
        batch_op.drop_column('schedule_enabled')

    op.drop_table('scheduler_runs')
    op.drop_table('evaluations')
    op.drop_table('forecast_runs')
    op.drop_table('models')
