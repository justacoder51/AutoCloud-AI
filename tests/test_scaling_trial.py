"""Mock cloud operations only; no infrastructure changes or accuracy claims."""

import copy
import json
from unittest.mock import Mock

import pytest

from app.services.cloudrun_service import CloudRunService
from app.services.scaling_trial import ScalingTrial


def setup(tmp_path):
    adapter = Mock()
    adapter.name = 'projects/test-project/locations/asia-south1/services/autocloud-api'
    resource = {'name': adapter.name, 'etag': 'first', 'uid': 'one',
                'terminalCondition': {'state': 'CONDITION_SUCCEEDED'},
                'template': {'scaling': {'maxInstanceCount': 2}}, 'scaling': {}}
    adapter.read.side_effect = lambda: copy.deepcopy(resource)
    adapter.minimum.return_value = {'name': 'operation-1', 'done': False}
    return ScalingTrial(adapter, tmp_path), adapter, resource


def test_apply_rollback_and_verified_restore(tmp_path):
    trial, adapter, resource = setup(tmp_path)
    plan = trial.prepare()
    trial.apply(plan, plan['approval_digest'])
    adapter.minimum.assert_called_once_with(resource, 1, validate_only=False)
    resource['etag'] = 'second'
    resource['scaling'] = {'minInstanceCount': 1}
    trial.rollback()
    assert adapter.minimum.call_args.args[1] == 0
    assert (trial.directory / 'active.json').exists()
    resource['scaling'] = {}
    resource['etag'] = 'third'
    assert trial.rollback()['restored']
    assert not (trial.directory / 'active.json').exists()
    assert 'rollback_verified' in (trial.directory / 'events.jsonl').read_text()


def test_approval_tampering_drift_and_active_experiment_block(tmp_path):
    trial, adapter, resource = setup(tmp_path)
    plan = trial.prepare()
    with pytest.raises(ValueError):
        trial.apply(plan, 'wrong')
    with pytest.raises(ValueError):
        trial.apply({**plan, 'during': 2}, plan['approval_digest'])
    resource['etag'] = 'changed'
    with pytest.raises(ValueError):
        trial.apply(plan, plan['approval_digest'])
    resource['etag'] = 'first'
    runs = tmp_path / 'training_runs'
    (runs / ('a'*32)).mkdir(parents=True)
    (runs / 'active.json').write_text(json.dumps({'run_id': 'a'*32}))
    (runs / ('a'*32) / 'status.json').write_text('{"stage":"sending_traffic"}')
    with pytest.raises(ValueError, match='active'):
        trial.apply(plan, plan['approval_digest'])
    adapter.minimum.assert_not_called()


def test_uncertain_apply_retains_recovery_record_and_blocks_retry(tmp_path):
    trial, adapter, _ = setup(tmp_path)
    plan = trial.prepare()
    adapter.minimum.side_effect = TimeoutError()
    with pytest.raises(TimeoutError):
        trial.apply(plan, plan['approval_digest'])
    assert (trial.directory / 'active.json').exists()
    with pytest.raises(FileExistsError):
        trial.apply(plan, plan['approval_digest'])
    assert adapter.minimum.call_count == 1


def test_rollback_does_not_overwrite_unrelated_change(tmp_path):
    trial, adapter, resource = setup(tmp_path)
    plan = trial.prepare()
    trial.apply(plan, plan['approval_digest'])
    resource['template']['image'] = 'new-revision'
    with pytest.raises(ValueError, match='drift'):
        trial.rollback()
    assert adapter.minimum.call_count == 1


@pytest.mark.parametrize('change', [
    {'reconciling': True}, {'terminalCondition': {'state': 'CONDITION_FAILED'}},
    {'template': {'scaling': {'maxInstanceCount': 10}}},
    {'scaling': {'scalingMode': 'MANUAL'}}, {'scaling': {'minInstanceCount': 1}},
])
def test_unsafe_baselines_rejected(tmp_path, change):
    trial, adapter, resource = setup(tmp_path)
    resource.update(change)
    with pytest.raises(ValueError):
        trial.prepare()
    adapter.minimum.assert_not_called()


def test_rest_adapter_uses_etag_exact_mask_and_validate_only_by_default():
    session = Mock()
    adapter = CloudRunService('test-project', 'asia-south1', 'autocloud-api', session)
    session.patch.return_value = Mock(status_code=200, json=lambda: {'done': True})
    adapter.minimum({'name': adapter.name, 'etag': 'concurrency'}, 1)
    kwargs = session.patch.call_args.kwargs
    assert kwargs['params'] == {'updateMask': 'scaling.minInstanceCount', 'validateOnly': 'true'}
    assert kwargs['json'] == {'name': adapter.name, 'etag': 'concurrency', 'scaling': {'minInstanceCount': 1}}
    with pytest.raises(ValueError):
        adapter.minimum({'name': adapter.name, 'etag': 'concurrency'}, 3)


def test_service_level_cap_without_revision_cap_is_supported(tmp_path):
    trial, _, resource = setup(tmp_path)
    resource['template'] = {}
    resource['scaling'] = {'maxInstanceCount': 2}
    assert trial.prepare()['during'] == 1
