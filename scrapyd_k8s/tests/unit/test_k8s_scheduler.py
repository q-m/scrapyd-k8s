import pytest
from unittest.mock import Mock, patch
from kubernetes.client.rest import ApiException
from scrapyd_k8s.k8s_scheduler.k8s_scheduler import KubernetesScheduler

@pytest.fixture
def mock_config():
    mock_config = Mock()
    mock_config.namespace.return_value = 'default'
    return mock_config

@pytest.fixture
def mock_launcher():
    mock_launcher = Mock()
    mock_launcher.LABEL_JOB_ID = 'org.scrapy.job_id'
    return mock_launcher

def test_k8s_scheduler_init(mock_config, mock_launcher):
    max_proc = 5
    scheduler = KubernetesScheduler(mock_config, mock_launcher, max_proc)
    assert scheduler.config == mock_config
    assert scheduler.launcher == mock_launcher
    assert scheduler.max_proc == max_proc
    assert scheduler.namespace == 'default'

def test_k8s_scheduler_init_invalid_max_proc(mock_config, mock_launcher):
    max_proc = 'five'  # Not an integer
    with pytest.raises(TypeError) as excinfo:
        KubernetesScheduler(mock_config, mock_launcher, max_proc)
    assert "max_proc must be an integer" in str(excinfo.value)

def test_handle_pod_event_with_non_dict_event(mock_config, mock_launcher):
    scheduler = KubernetesScheduler(mock_config, mock_launcher, 5)
    event = ['not', 'a', 'dict']
    with patch('scrapyd_k8s.k8s_scheduler.k8s_scheduler.logger') as mock_logger:
        scheduler.handle_pod_event(event)
        mock_logger.error.assert_called_with(
            f"TypeError in handle_pod_event: Event must be a dictionary, got {type(event).__name__} in event: {event}"
        )

def test_handle_pod_event_missing_keys(mock_config, mock_launcher):
    scheduler = KubernetesScheduler(mock_config, mock_launcher, 5)
    event = {'wrong_key': 'value'}
    with patch('scrapyd_k8s.k8s_scheduler.k8s_scheduler.logger') as mock_logger:
        scheduler.handle_pod_event(event)
        mock_logger.error.assert_called_with(
            f"KeyError in handle_pod_event: Missing key 'object' in event: {event}"
        )

def test_handle_pod_event_pod_missing_status(mock_config, mock_launcher):
    scheduler = KubernetesScheduler(mock_config, mock_launcher, 5)
    pod = Mock()
    pod.status = None
    pod.metadata = Mock()
    pod.metadata.name = 'pod-name'
    event = {'object': pod, 'type': 'MODIFIED'}
    with patch('scrapyd_k8s.k8s_scheduler.k8s_scheduler.logger') as mock_logger:
        scheduler.handle_pod_event(event)
        mock_logger.error.assert_called_with(
            f"AttributeError in handle_pod_event: 'NoneType' object has no attribute 'phase' in event: {event}"
        )

def test_handle_pod_event_pod_missing_metadata(mock_config, mock_launcher):
    scheduler = KubernetesScheduler(mock_config, mock_launcher, 5)
    pod = Mock()
    pod.status = Mock()
    pod.status.phase = 'Running'
    pod.metadata = None
    event = {'object': pod, 'type': 'MODIFIED'}
    with patch('scrapyd_k8s.k8s_scheduler.k8s_scheduler.logger') as mock_logger:
        scheduler.handle_pod_event(event)
        mock_logger.error.assert_called_with(
            f"AttributeError in handle_pod_event: 'NoneType' object has no attribute 'name' in event: {event}"
        )

def test_handle_pod_event_pod_not_related(mock_config, mock_launcher):
    scheduler = KubernetesScheduler(mock_config, mock_launcher, 5)
    pod = Mock()
    pod.status = Mock()
    pod.status.phase = 'Running'
    pod.metadata = Mock()
    pod.metadata.name = 'pod-name'
    pod.metadata.labels = {}
    event = {'object': pod, 'type': 'MODIFIED'}
    with patch('scrapyd_k8s.k8s_scheduler.k8s_scheduler.logger') as mock_logger:
        scheduler.handle_pod_event(event)
        mock_logger.debug.assert_called_with("Pod pod-name does not have our job label; ignoring.")

def test_handle_pod_event_pod_terminated(mock_config, mock_launcher):
    scheduler = KubernetesScheduler(mock_config, mock_launcher, 5)
    pod = Mock()
    pod.status = Mock()
    pod.status.phase = 'Succeeded'
    pod.metadata = Mock()
    pod.metadata.name = 'pod-name'
    pod.metadata.labels = {mock_launcher.LABEL_JOB_ID: 'job-id'}
    event = {'object': pod, 'type': 'MODIFIED'}

    with patch.object(scheduler, 'check_and_unsuspend_jobs') as mock_check_and_unsuspend_jobs, \
         patch('scrapyd_k8s.k8s_scheduler.k8s_scheduler.logger') as mock_logger:
        scheduler.handle_pod_event(event)
        mock_logger.info.assert_called_with(
            "Pod pod-name has completed with phase Succeeded. Checking for suspended jobs."
        )
        mock_check_and_unsuspend_jobs.assert_called_once()

def test_handle_pod_event_pod_not_terminated(mock_config, mock_launcher):
    scheduler = KubernetesScheduler(mock_config, mock_launcher, 5)
    pod = Mock()
    pod.status = Mock()
    pod.status.phase = 'Running'
    pod.metadata = Mock()
    pod.metadata.name = 'pod-name'
    pod.metadata.labels = {mock_launcher.LABEL_JOB_ID: 'job-id'}
    event = {'object': pod, 'type': 'MODIFIED'}

    with patch.object(scheduler, 'check_and_unsuspend_jobs') as mock_check_and_unsuspend_jobs, \
         patch('scrapyd_k8s.k8s_scheduler.k8s_scheduler.logger') as mock_logger:
        scheduler.handle_pod_event(event)
        mock_logger.debug.assert_called_with("Pod pod-name event not relevant for unsuspension.")
        mock_check_and_unsuspend_jobs.assert_not_called()

def test_check_and_unsuspend_jobs_with_capacity_and_suspended_jobs(mock_config, mock_launcher):
    scheduler = KubernetesScheduler(mock_config, mock_launcher, 5)

    mock_launcher.get_running_jobs_count.return_value = 3
    scheduler.get_next_suspended_job_id = Mock(side_effect=['job1', 'job2', None])
    mock_launcher.unsuspend_job.side_effect = [True, True]

    with patch('scrapyd_k8s.k8s_scheduler.k8s_scheduler.logger') as mock_logger:
        scheduler.check_and_unsuspend_jobs()
        assert mock_launcher.unsuspend_job.call_count == 2
        mock_launcher.unsuspend_job.assert_any_call('job1')
        mock_launcher.unsuspend_job.assert_any_call('job2')
        mock_logger.info.assert_any_call("Unsuspended job job1. Total running jobs now: 4")
        mock_logger.info.assert_any_call("Unsuspended job job2. Total running jobs now: 5")

def test_check_and_unsuspend_jobs_no_suspended_jobs(mock_config, mock_launcher):
    scheduler = KubernetesScheduler(mock_config, mock_launcher, 5)

    mock_launcher.get_running_jobs_count.return_value = 3
    scheduler.get_next_suspended_job_id = Mock(return_value=None)

    with patch('scrapyd_k8s.k8s_scheduler.k8s_scheduler.logger') as mock_logger:
        scheduler.check_and_unsuspend_jobs()
        mock_launcher.unsuspend_job.assert_not_called()
        mock_logger.info.assert_called_with("No suspended jobs to unsuspend.")

def test_check_and_unsuspend_jobs_unsuspend_fails(mock_config, mock_launcher):
    scheduler = KubernetesScheduler(mock_config, mock_launcher, 5)

    mock_launcher.get_running_jobs_count.return_value = 3
    scheduler.get_next_suspended_job_id = Mock(return_value='job1')
    mock_launcher.unsuspend_job.return_value = False

    with patch('scrapyd_k8s.k8s_scheduler.k8s_scheduler.logger') as mock_logger:
        scheduler.check_and_unsuspend_jobs()
        mock_launcher.unsuspend_job.assert_called_once_with('job1')
        mock_logger.error.assert_called_with("Failed to unsuspend job job1")

def test_check_and_unsuspend_jobs_unsuspend_api_exception(mock_config, mock_launcher):
    scheduler = KubernetesScheduler(mock_config, mock_launcher, 5)

    mock_launcher.get_running_jobs_count.return_value = 3
    scheduler.get_next_suspended_job_id = Mock(return_value='job1')
    mock_launcher.unsuspend_job.side_effect = ApiException("API Error")

    with patch('scrapyd_k8s.k8s_scheduler.k8s_scheduler.logger') as mock_logger:
        scheduler.check_and_unsuspend_jobs()
        mock_launcher.unsuspend_job.assert_called_once_with('job1')
        mock_logger.error.assert_called_with(
            f"Kubernetes API exception while unsuspending job job1: (API Error)\nReason: None\n"
        )

def test_get_next_suspended_job_id_with_suspended_jobs(mock_config, mock_launcher):
    scheduler = KubernetesScheduler(mock_config, mock_launcher, 5)

    job1 = Mock()
    job1.metadata = Mock()
    job1.metadata.creation_timestamp = '2021-01-01T00:00:00Z'
    job1.metadata.labels = {mock_launcher.LABEL_JOB_ID: 'job1'}

    job2 = Mock()
    job2.metadata = Mock()
    job2.metadata.creation_timestamp = '2021-01-02T00:00:00Z'
    job2.metadata.labels = {mock_launcher.LABEL_JOB_ID: 'job2'}

    mock_launcher.list_suspended_jobs.return_value = [job2, job1]

    with patch('scrapyd_k8s.k8s_scheduler.k8s_scheduler.logger') as mock_logger:
        job_id = scheduler.get_next_suspended_job_id()
        assert job_id == 'job1'
        mock_logger.debug.assert_called_with("Next suspended job to unsuspend: job1")

def test_get_next_suspended_job_id_no_suspended_jobs(mock_config, mock_launcher):
    scheduler = KubernetesScheduler(mock_config, mock_launcher, 5)

    mock_launcher.list_suspended_jobs.return_value = []

    with patch('scrapyd_k8s.k8s_scheduler.k8s_scheduler.logger') as mock_logger:
        job_id = scheduler.get_next_suspended_job_id()
        assert job_id is None
        mock_logger.debug.assert_called_with("No suspended jobs found.")

def test_get_next_suspended_job_id_list_suspended_jobs_returns_non_list(mock_config, mock_launcher):
    scheduler = KubernetesScheduler(mock_config, mock_launcher, 5)

    mock_launcher.list_suspended_jobs.return_value = 'not a list'

    with patch('scrapyd_k8s.k8s_scheduler.k8s_scheduler.logger') as mock_logger:
        job_id = scheduler.get_next_suspended_job_id()
        assert job_id is None
        mock_logger.error.assert_called_with(
            "TypeError in get_next_suspended_job_id: list_suspended_jobs should return a list, got str"
        )

def test_get_next_suspended_job_id_job_missing_creation_timestamp(mock_config, mock_launcher):
    scheduler = KubernetesScheduler(mock_config, mock_launcher, 5)

    job = Mock()
    job.metadata = Mock()
    job.metadata.labels = {mock_launcher.LABEL_JOB_ID: 'job1'}
    job.metadata.creation_timestamp = None  # Simulate missing creation_timestamp

    mock_launcher.list_suspended_jobs.return_value = [job]

    with patch('scrapyd_k8s.k8s_scheduler.k8s_scheduler.logger') as mock_logger:
        job_id = scheduler.get_next_suspended_job_id()
        assert job_id == 'job1'
        mock_logger.warning.assert_called_with(
            f"Job {job} missing 'metadata.creation_timestamp'; assigned max timestamp."
        )
