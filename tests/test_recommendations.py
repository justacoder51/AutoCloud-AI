"""Synthetic fixtures test policy boundaries, not real anomaly accuracy."""

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.agents.recommendation_agent import build_plan
from app.agents.validation import validate_recommendation
from app.data.schema import MetricRecord

NOW = datetime(2026, 11, 15, 15, tzinfo=timezone.utc)
TARGET = dict(project="test-project", region="asia-south1", service="fixture-service")


def records(**values):
    return [MetricRecord(
        timestamp=NOW - timedelta(minutes=minute), collected_at=NOW,
        project_id=TARGET["project"], region=TARGET["region"],
        service_name=TARGET["service"], **values,
    ) for minute in (5, 4, 3)]


def plan(rows):
    return build_plan(rows, **TARGET, now=NOW)


def test_sustained_pressure_has_exact_evidence_and_no_execution_or_savings():
    rows = records(cpu_utilization=.95, memory_utilization=.96, error_rate=.1)
    result = plan(rows)
    assert result.data_status == "fresh"
    assert {item.action for item in result.recommendations} == {
        "review_capacity", "investigate_memory", "investigate_errors",
    }
    for item in result.recommendations:
        assert item.evidence.record_ids == tuple(record.record_id for record in rows)
        assert item.confidence is item.estimated_financial_impact is None
        assert item.execution_allowed is False
        assert item.approval_status == "pending_review"
        assert validate_recommendation(item.model_dump(mode="json"), rows, **TARGET, now=NOW) == item
    assert result.model_status == result.cost_status == "not_evaluated"


def test_missing_and_zero_are_distinct_and_do_not_create_a_breach():
    missing, measured = plan(records()), plan(records(cpu_utilization=0, error_rate=0))
    assert missing.recommendations == measured.recommendations == ()
    assert "missing values" in missing.diagnostic
    assert missing.evidence_fingerprint != measured.evidence_fingerprint


def test_one_spike_or_one_missing_value_does_not_establish_sustained_pressure():
    rows = records(cpu_utilization=.95)
    rows[-1] = rows[-1].model_copy(update={"cpu_utilization": None})
    assert not plan(rows).recommendations
    rows[-1] = rows[-1].model_copy(update={"cpu_utilization": .1})
    assert not plan(rows).recommendations


@pytest.mark.parametrize("kind", ["stale", "insufficient", "incomplete_window"])
def test_unusable_history_returns_diagnostic_without_action(kind):
    rows = records(cpu_utilization=.95)
    if kind == "stale":
        result = build_plan(rows, **TARGET, now=NOW + timedelta(hours=1))
    elif kind == "insufficient":
        result = plan(rows[:2])
    else:
        rows[0] = MetricRecord(**{
            **rows[0].model_dump(), "timestamp": NOW - timedelta(minutes=6),
        })
        result = plan(rows)
    assert result.data_status == kind
    assert not result.recommendations


def test_repeated_polls_do_not_count_as_extra_observed_minutes():
    row = records(cpu_utilization=.99)[0]
    assert plan([row] * 20).data_status == "insufficient"


def test_latest_collection_wins_and_same_time_conflicts_are_rejected():
    rows = records(cpu_utilization=.95)
    old = rows[-1].model_copy(update={
        "cpu_utilization": .1, "collected_at": NOW - timedelta(minutes=1),
    })
    assert plan([old, *rows]) == plan([*rows, old])
    conflict = rows[-1].model_copy(update={"cpu_utilization": .2})
    with pytest.raises(ValueError, match="Conflicting"):
        plan([*rows, conflict])


def test_mixed_target_future_evidence_and_naive_clock_are_rejected():
    row = records()[0]
    for update in ({"project_id": "other"}, {"region": "other"},
                   {"service_name": "other"}, {"timestamp": NOW + timedelta(minutes=1)},
                   {"collected_at": NOW + timedelta(minutes=1)}):
        with pytest.raises(ValueError):
            plan([row.model_copy(update=update)])
    with pytest.raises(ValueError, match="timezone aware"):
        build_plan([], **TARGET, now=NOW.replace(tzinfo=None))


@pytest.mark.parametrize("change", ["evidence", "action", "problem", "impact", "confidence", "execute"])
def test_untrusted_proposals_cannot_invent_evidence_actions_costs_or_confidence(change):
    rows = records(cpu_utilization=.95)
    draft = plan(rows).recommendations[0].model_dump(mode="json")
    if change == "evidence":
        draft["evidence"]["values"][0] = .99
    elif change == "action":
        draft["action"] = "run_arbitrary_shell_command"
    elif change == "problem":
        draft["problem"] = "Confirmed CPU bottleneck caused by a memory leak"
    elif change == "impact":
        draft["estimated_financial_impact"] = 500
    elif change == "confidence":
        draft["confidence"] = .99
    else:
        draft["execution_allowed"] = True
    with pytest.raises((ValueError, ValidationError)):
        validate_recommendation(draft, rows, **TARGET, now=NOW)


def test_old_valid_proposal_is_rejected_after_evidence_expires_or_changes():
    rows = records(cpu_utilization=.95)
    draft = plan(rows).recommendations[0].model_dump(mode="json")
    with pytest.raises(ValueError):
        validate_recommendation(draft, rows, **TARGET, now=NOW + timedelta(hours=1))
    with pytest.raises(ValueError):
        validate_recommendation(draft, records(cpu_utilization=.1), **TARGET, now=NOW)
