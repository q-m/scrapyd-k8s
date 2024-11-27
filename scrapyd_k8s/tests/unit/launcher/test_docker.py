import pytest
from unittest.mock import MagicMock, patch
import time
from scrapyd_k8s.launcher.docker import Docker

@pytest.fixture
def config_with_max_proc():
    config = MagicMock()
    config.scrapyd.return_value.get.return_value = '2'  # max_proc set to 2
    return config

@pytest.fixture
def config_without_max_proc():
    config = MagicMock()
    config.scrapyd.return_value.get.return_value = None  # max_proc not set
    return config

@pytest.fixture
def mock_docker_client():
    with patch('scrapyd_k8s.launcher.docker.docker') as mock_docker_module:
        mock_client = MagicMock()
        mock_docker_module.from_env.return_value = mock_client
        yield mock_client

@pytest.fixture
def docker_launcher_with_max_proc(config_with_max_proc, mock_docker_client):
    return Docker(config_with_max_proc)

@pytest.fixture
def docker_launcher_without_max_proc(config_without_max_proc, mock_docker_client):
    return Docker(config_without_max_proc)

def test_docker_init_with_max_proc(config_with_max_proc, mock_docker_client):
    docker_launcher = Docker(config_with_max_proc)
    assert docker_launcher.max_proc == 2
    assert docker_launcher._thread is not None
    assert docker_launcher._thread.is_alive()

def test_docker_init_without_max_proc(config_without_max_proc, mock_docker_client):
    docker_launcher = Docker(config_without_max_proc)
    assert docker_launcher.max_proc is None
    assert docker_launcher._thread is None

def test_schedule_with_capacity(docker_launcher_with_max_proc, mock_docker_client):
    # Mock methods
    docker_launcher_with_max_proc.get_running_jobs_count = MagicMock(return_value=1)
    docker_launcher_with_max_proc.start_pending_containers = MagicMock()

    # Mock container creation
    mock_container = MagicMock()
    mock_docker_client.containers.create.return_value = mock_container

    # Prepare parameters for schedule
    project = MagicMock()
    project.id.return_value = 'test_project'
    project.repository.return_value = 'test_repo'
    project.resources.return_value = {}
    version = 'v1'
    spider = 'test_spider'
    job_id = 'job_123'
    settings = {}
    args = {}

    # Call schedule
    docker_launcher_with_max_proc.schedule(project, version, spider, job_id, settings, args)

    # Verify that container is created
    mock_docker_client.containers.create.assert_called_once()

    # Since running jobs count is less than max_proc, start_pending_containers should be called
    docker_launcher_with_max_proc.start_pending_containers.assert_called_once()

def test_schedule_no_capacity(docker_launcher_with_max_proc, mock_docker_client):
    # Mock methods
    docker_launcher_with_max_proc.get_running_jobs_count = MagicMock(return_value=2)  # At max_proc
    docker_launcher_with_max_proc.start_pending_containers = MagicMock()

    # Mock container creation
    mock_container = MagicMock()
    mock_docker_client.containers.create.return_value = mock_container

    # Prepare parameters for schedule
    project = MagicMock()
    project.id.return_value = 'test_project'
    project.repository.return_value = 'test_repo'
    project.resources.return_value = {}
    version = 'v1'
    spider = 'test_spider'
    job_id = 'job_456'
    settings = {}
    args = {}

    # Patch the logger to check log outputs
    with patch('scrapyd_k8s.launcher.docker.logger') as mock_logger:
        # Call schedule
        docker_launcher_with_max_proc.schedule(project, version, spider, job_id, settings, args)

        # Verify that container is created
        mock_docker_client.containers.create.assert_called_once()

        # start_pending_containers should not be called since we're at capacity
        docker_launcher_with_max_proc.start_pending_containers.assert_not_called()

        # Verify that container.start() is not called immediately
        mock_container.start.assert_not_called()

        # Check that the correct log message was output
        mock_logger.info.assert_called_with(f"Job {job_id} is pending due to max_proc limit.")

def test_schedule_no_max_proc(docker_launcher_without_max_proc, mock_docker_client):
    # Mock container creation
    mock_container = MagicMock()
    mock_docker_client.containers.create.return_value = mock_container

    # Prepare parameters for schedule
    project = MagicMock()
    project.id.return_value = 'test_project'
    project.repository.return_value = 'test_repo'
    project.resources.return_value = {}
    version = 'v1'
    spider = 'test_spider'
    job_id = 'job_789'
    settings = {}
    args = {}

    # Call schedule
    docker_launcher_without_max_proc.schedule(project, version, spider, job_id, settings, args)

    # Verify that container is created
    mock_docker_client.containers.create.assert_called_once()

    # Since max_proc is not set, container.start() should be called immediately
    mock_container.start.assert_called_once()

def test_get_running_jobs_count(docker_launcher_with_max_proc, mock_docker_client):
    # Mock the list of running containers
    mock_container_list = [MagicMock(), MagicMock()]
    mock_docker_client.containers.list.return_value = mock_container_list

    count = docker_launcher_with_max_proc.get_running_jobs_count()

    # Verify that the count matches the number of mock containers
    assert count == 2
    mock_docker_client.containers.list.assert_called_with(
        filters={'label': docker_launcher_with_max_proc.LABEL_PROJECT, 'status': 'running'})

def test_start_pending_containers(docker_launcher_with_max_proc, mock_docker_client):
    # Mock the get_running_jobs_count method
    docker_launcher_with_max_proc.get_running_jobs_count = MagicMock(return_value=1)

    # Mock pending containers
    mock_pending_container = MagicMock()
    mock_pending_container.name = 'pending_container'
    mock_docker_client.containers.list.return_value = [mock_pending_container]

    # Patch logger to check log outputs
    with patch('scrapyd_k8s.launcher.docker.logger') as mock_logger:
        # Call start_pending_containers
        docker_launcher_with_max_proc.start_pending_containers()

        # Verify that the pending container's start method was called
        mock_pending_container.start.assert_called_once()

        # Verify that the correct log message was output
        mock_logger.info.assert_called_with(
            f"Started pending container {mock_pending_container.name}. Total running jobs now: 2"
        )

def test_background_task_starts_pending_containers(config_with_max_proc, mock_docker_client):
    # Mock start_pending_containers before initializing the Docker class
    with patch.object(Docker, 'start_pending_containers', autospec=True) as mock_start_pending:
        # Initialize Docker instance
        docker_launcher = Docker(config_with_max_proc)

        # Wait for slightly more than check_interval to ensure the background task runs
        time.sleep(5.1)  # Wait for the background thread to execute

        # Verify that start_pending_containers was called by the background thread
        assert mock_start_pending.call_count > 0

        # Clean up by shutting down the background thread
        docker_launcher.shutdown()
