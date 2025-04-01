import pytest
from unittest.mock import Mock, patch
from kubernetes.client.rest import ApiException
from scrapyd_k8s.launcher.k8s_scheduler import KubernetesScheduler

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

class TestKubernetesSchedulerInitialization:
    def test_k8s_scheduler_init(self, mock_config, mock_launcher):
        max_proc = 5
        scheduler = KubernetesScheduler(mock_config, mock_launcher, max_proc)
        assert scheduler.config == mock_config
        assert scheduler.launcher == mock_launcher
        assert scheduler.max_proc == max_proc
        assert scheduler.namespace == 'default'

    def test_k8s_scheduler_init_invalid_max_proc(self, mock_config, mock_launcher):
        max_proc = 'five'  # Not an integer
        with pytest.raises(TypeError) as excinfo:
            KubernetesScheduler(mock_config, mock_launcher, max_proc)
        assert "max_proc must be an integer" in str(excinfo.value)


class TestPodEventHandling:
    @pytest.mark.parametrize("event, expected_log, log_type", [
        (
                ['not', 'a', 'dict'],
                "TypeError in handle_pod_event: Event must be a dictionary, got list in event: ['not', 'a', 'dict']",
                'error'
        ),
        (
                {'wrong_key': 'value'},
                "KeyError in handle_pod_event: Missing key 'object' in event: {'wrong_key': 'value'}",
                'error'
        ),
    ])
    def test_handle_pod_event_input_validation(self, mock_config, mock_launcher, event, expected_log, log_type):
        scheduler = KubernetesScheduler(mock_config, mock_launcher, 5)
        with patch('scrapyd_k8s.launcher.k8s_scheduler.k8s_scheduler.logger') as mock_logger:
            scheduler.handle_pod_event(event)
            if log_type == 'error':
                mock_logger.error.assert_called_with(expected_log)
            elif log_type == 'debug':
                mock_logger.debug.assert_called_with(expected_log)
            elif log_type == 'info':
                mock_logger.info.assert_called_with(expected_log)

    @pytest.mark.parametrize("pod_config, expected_log, log_type", [
        # Pod with missing status
        (
                {"status": None, "metadata_name": "pod-name", "metadata_labels": {}},
                "AttributeError in handle_pod_event: 'NoneType' object has no attribute 'phase' in event: ",
                'error'
        ),
        # Pod with missing metadata
        (
                {"status_phase": "Running", "metadata": None},
                "AttributeError in handle_pod_event: 'NoneType' object has no attribute 'name' in event: ",
                'error'
        ),
        # Pod not related to our jobs
        (
                {"status_phase": "Running", "metadata_name": "pod-name", "metadata_labels": {}},
                "Pod pod-name does not have our job label; ignoring.",
                'debug'
        ),
        # Pod terminated successfully
        (
                {"status_phase": "Succeeded", "metadata_name": "pod-name",
                 "metadata_labels": {"org.scrapy.job_id": "job-id"}},
                "Pod pod-name has completed with phase Succeeded. Checking for suspended jobs.",
                'info'
        ),
        # Pod not terminated
        (
                {"status_phase": "Running", "metadata_name": "pod-name",
                 "metadata_labels": {"org.scrapy.job_id": "job-id"}},
                "Pod pod-name event not relevant for unsuspension.",
                'debug'
        ),
    ])
    def test_handle_pod_event_pod_scenarios(self, mock_config, mock_launcher, pod_config, expected_log, log_type):
        scheduler = KubernetesScheduler(mock_config, mock_launcher, 5)

        # Create a mock pod based on the configuration
        pod = Mock()

        if "status" in pod_config:
            pod.status = pod_config["status"]
        else:
            pod.status = Mock()
            if "status_phase" in pod_config:
                pod.status.phase = pod_config["status_phase"]

        if "metadata" in pod_config:
            pod.metadata = pod_config["metadata"]
        else:
            pod.metadata = Mock()
            if "metadata_name" in pod_config:
                pod.metadata.name = pod_config["metadata_name"]
            if "metadata_labels" in pod_config:
                pod.metadata.labels = pod_config["metadata_labels"]

        event = {'object': pod, 'type': 'MODIFIED'}

        with patch('scrapyd_k8s.launcher.k8s_scheduler.k8s_scheduler.logger') as mock_logger, \
                patch.object(scheduler, 'check_and_unsuspend_jobs') as mock_check_and_unsuspend_jobs:
            scheduler.handle_pod_event(event)

            if log_type == 'error':
                # For error logs, we need to check that it contains the expected text since
                # the full event will be appended
                assert mock_logger.error.call_count == 1
                assert expected_log in mock_logger.error.call_args[0][0]
            elif log_type == 'debug':
                mock_logger.debug.assert_called_with(expected_log)
            elif log_type == 'info':
                mock_logger.info.assert_called_with(expected_log)

            # Check if check_and_unsuspend_jobs should be called
            if pod_config.get("status_phase") in ["Succeeded", "Failed"] and \
                    pod_config.get("metadata_labels", {}).get(mock_launcher.LABEL_JOB_ID):
                mock_check_and_unsuspend_jobs.assert_called_once()
            else:
                mock_check_and_unsuspend_jobs.assert_not_called()


class TestJobSuspensionManagement:
    @pytest.mark.parametrize("running_count, suspended_jobs, unsuspend_results, expected_logs", [
        # Case with capacity and suspended jobs
        (
                3,  # running_count
                ['job1', 'job2', None],  # suspended_jobs
                [True, True],  # unsuspend_results
                [
                    "Unsuspended job job1. Total running jobs now: 4",
                    "Unsuspended job job2. Total running jobs now: 5"
                ]  # expected_logs
        ),
        # Case with no suspended jobs
        (
                3,  # running_count
                [None],  # suspended_jobs
                [],  # unsuspend_results
                ["No suspended jobs to unsuspend."]  # expected_logs
        ),
        # Case where unsuspension fails
        (
                3,  # running_count
                ['job1'],  # suspended_jobs
                [False],  # unsuspend_results
                ["Failed to unsuspend job job1"]  # expected_logs
        )
    ])
    def test_check_and_unsuspend_jobs_scenarios(self, mock_config, mock_launcher,
                                                running_count, suspended_jobs,
                                                unsuspend_results, expected_logs):
        scheduler = KubernetesScheduler(mock_config, mock_launcher, 5)

        mock_launcher.get_running_jobs_count.return_value = running_count
        scheduler.get_next_suspended_job_id = Mock(side_effect=suspended_jobs)
        mock_launcher.unsuspend_job.side_effect = unsuspend_results

        with patch('scrapyd_k8s.launcher.k8s_scheduler.k8s_scheduler.logger') as mock_logger:
            scheduler.check_and_unsuspend_jobs()

            assert mock_launcher.unsuspend_job.call_count == len(unsuspend_results)

            # Verify the logs
            log_methods = {
                "Failed to unsuspend job": mock_logger.error,
                "No suspended jobs to unsuspend": mock_logger.info,
                "Unsuspended job": mock_logger.info
            }

            for expected_log in expected_logs:
                for prefix, log_method in log_methods.items():
                    if expected_log.startswith(prefix):
                        assert any(
                            expected_log in call_args[0][0]
                            for call_args in log_method.call_args_list
                        )

    def test_check_and_unsuspend_jobs_unsuspend_api_exception(self, mock_config, mock_launcher):
        scheduler = KubernetesScheduler(mock_config, mock_launcher, 5)

        mock_launcher.get_running_jobs_count.return_value = 3
        scheduler.get_next_suspended_job_id = Mock(return_value='job1')
        mock_launcher.unsuspend_job.side_effect = ApiException("API Error")

        with patch('scrapyd_k8s.launcher.k8s_scheduler.k8s_scheduler.logger') as mock_logger:
            scheduler.check_and_unsuspend_jobs()
            mock_launcher.unsuspend_job.assert_called_once_with('job1')
            mock_logger.error.assert_called_with(
                f"Kubernetes API exception while unsuspending job job1: (API Error)\nReason: None\n"
            )


class TestSuspendedJobSelection:
    @pytest.mark.parametrize("suspended_jobs, expected_job_id, expected_log, log_type", [
        # Case with suspended jobs - should return the oldest job (job1)
        (
                [
                    # job2 is newer
                    {'id': 'job2', 'creation_timestamp': '2021-01-02T00:00:00Z'},
                    # job1 is older
                    {'id': 'job1', 'creation_timestamp': '2021-01-01T00:00:00Z'}
                ],
                'job1',
                "Next suspended job to unsuspend: job1",
                'debug'
        ),
        # Case with no suspended jobs
        (
                [],
                None,
                "No suspended jobs found.",
                'debug'
        ),
        # Case with non-list return value
        (
                'not a list',
                None,
                "TypeError in get_next_suspended_job_id: list_suspended_jobs should return a list, got str",
                'error'
        ),
        # Case with job missing creation timestamp
        (
                [{'id': 'job1', 'creation_timestamp': None}],
                'job1',
                "Job .* missing 'metadata.creation_timestamp'; assigned max timestamp.",
                'warning'
        ),
    ])
    def test_get_next_suspended_job_id_scenarios(self, mock_config, mock_launcher,
                                                 suspended_jobs, expected_job_id,
                                                 expected_log, log_type):
        scheduler = KubernetesScheduler(mock_config, mock_launcher, 5)

        # Handle special case for non-list
        if suspended_jobs == 'not a list':
            mock_launcher.list_suspended_jobs.return_value = suspended_jobs
        else:
            # Create proper mock jobs based on the test data
            mock_jobs = []
            for job_data in suspended_jobs:
                job = Mock()
                job.metadata = Mock()
                job.metadata.creation_timestamp = job_data['creation_timestamp']
                job.metadata.labels = {mock_launcher.LABEL_JOB_ID: job_data['id']}
                mock_jobs.append(job)

            mock_launcher.list_suspended_jobs.return_value = mock_jobs

        with patch('scrapyd_k8s.launcher.k8s_scheduler.k8s_scheduler.logger') as mock_logger:
            job_id = scheduler.get_next_suspended_job_id()
            assert job_id == expected_job_id

            if log_type == 'debug':
                mock_logger.debug.assert_called_with(expected_log)
            elif log_type == 'error':
                mock_logger.error.assert_called_with(expected_log)
            elif log_type == 'warning':
                import re
                assert any(re.match(expected_log, args[0]) for args, _ in mock_logger.warning.call_args_list)
