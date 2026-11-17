"""Offline checks for background-run bounds and readiness-gated training."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.data import training_experiment as experiment
from app.data.schema import MetricRecord
from app.data.storage import save_records


def test_training_plan_keeps_per_block_caps_and_aggregate_budget():
    phases = experiment.planned_phases()
    assert len(phases) == 7
    assert sum(plan.duration_seconds for plan in phases) == 210 * 60
    assert sum(plan.request_budget for plan in phases) == 2100
    assert max(plan.requests_per_minute for plan in phases) == 14
    assert all(plan.max_requests <= 1000 and plan.duration_seconds <= 3600 for plan in phases)


def row(timestamp):
    return MetricRecord(
        timestamp=timestamp, collected_at=timestamp + timedelta(minutes=5),
        project_id=experiment.PROJECT, region=experiment.REGION, service_name=experiment.SERVICE,
    )


def test_cohort_excludes_old_history_and_partially_exposed_boundary_minutes():
    start = datetime(2026, 11, 15, 12, 0, 20, tzinfo=timezone.utc)
    end = start + timedelta(minutes=210)
    times = [start.replace(second=0) + timedelta(minutes=offset) for offset in (-10, 1, 2, 210, 211)]
    result = experiment.select_cohort([row(point) for point in times], start, end)
    assert [item.timestamp for item in result] == [times[2], times[3]]


@pytest.mark.parametrize("trained", [True, False])
def test_background_run_collects_its_own_cohort_and_keeps_training_outcome_truthful(monkeypatch, tmp_path, trained):
    monkeypatch.setattr(experiment, "RUNS", tmp_path / "runs")
    clock = {"now": 0.}
    begin = datetime(2026, 11, 15, 12, tzinfo=timezone.utc)

    class FixtureDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return begin + timedelta(seconds=clock["now"])

    monkeypatch.setattr(experiment, "datetime", FixtureDateTime)
    monkeypatch.setattr(experiment.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(experiment.time, "sleep", lambda seconds: clock.update(now=clock["now"] + seconds))

    def traffic(plan, **kwargs):
        clock["now"] += plan.duration_seconds
        return {
            "status": "completed", "attempted_requests": plan.request_budget,
            "successful_requests": plan.request_budget,
        }

    monkeypatch.setattr(experiment, "run_traffic", traffic)
    commands = []

    def command(arguments, timeout):
        commands.append(arguments)
        if arguments[0] == "app.data.collector":
            output = Path(next(arg.split("=", 1)[1] for arg in arguments if arg.startswith("--output=")))
            save_records([row(begin + timedelta(minutes=i)) for i in range(-5, 216)], output)
            return {"exit_code": 0, "result": {"status": "collected"}}
        assert arguments[0] == "app.models.train"
        assert "--profile=exploratory" in arguments and "--train" in arguments
        baseline = Path(next(arg.split("=", 1)[1] for arg in arguments if arg.startswith("--input=")))
        records = [MetricRecord.model_validate_json(line) for line in baseline.read_text().splitlines()]
        assert len(records) == 209
        assert records[0].timestamp == begin + timedelta(minutes=2)
        return {"exit_code": 0 if trained else 2, "result": {"trained": trained}}

    monkeypatch.setattr(experiment, "run_command", command)
    assert experiment.execute() == (0 if trained else 2)
    status = experiment.read_status(experiment.active_directory())
    assert status["stage"] == ("completed" if trained else "training_not_ready")
    assert status["trained"] is trained
    assert status["attempted_requests"] == status["successful_requests"] == 2100
    assert status["deployment_allowed"] is False
    assert len(commands) == 2
    assert 215 * 60 <= clock["now"] < 215 * 60 + 10


def test_duplicate_background_run_does_not_start_more_traffic(monkeypatch, tmp_path):
    monkeypatch.setattr(experiment, "RUNS", tmp_path)
    run_id = "a" * 32
    directory = tmp_path / run_id
    directory.mkdir()
    (tmp_path / "active.json").write_text('{"run_id":"' + run_id + '"}')
    experiment.write_status(directory, {}, stage="sending_traffic")
    traffic = Mock()
    monkeypatch.setattr(experiment, "run_traffic", traffic)
    with pytest.raises(ValueError, match="already active"):
        experiment.execute()
    traffic.assert_not_called()


def test_http_failure_stops_whole_experiment_before_collection_or_training(monkeypatch, tmp_path):
    monkeypatch.setattr(experiment, "RUNS", tmp_path)
    traffic = Mock(return_value={
        "status": "stopped_http_error", "attempted_requests": 1, "successful_requests": 0,
    })
    monkeypatch.setattr(experiment, "run_traffic", traffic)
    command = Mock()
    monkeypatch.setattr(experiment, "run_command", command)
    assert experiment.execute() == 1
    assert experiment.read_status(experiment.active_directory())["stage"] == "failed"
    traffic.assert_called_once()
    command.assert_not_called()
