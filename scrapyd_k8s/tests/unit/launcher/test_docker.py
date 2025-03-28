import pytest
from unittest.mock import Mock, patch
import time
from scrapyd_k8s.launcher.docker import Docker


@pytest.fixture
def config_factory():
    def _config(max_proc=None):
        config = Mock()
        config.scrapyd.return_value.get.return_value = str(max_proc) if max_proc is not None else None
        return config

    return _config


@pytest.fixture
def mock_docker_client():
    with patch('scrapyd_k8s.launcher.docker.docker') as mock_docker_module:
        mock_client = Mock()
        mock_docker_module.from_env.return_value = mock_client
        yield mock_client

@pytest.fixture
def docker_launcher_factory(config_factory, mock_docker_client):
    # Patch the threading module to prevent real threads from being created
    with patch('threading.Thread') as mock_thread_class:
        mock_thread = Mock()
        mock_thread.is_alive.return_value = True
        mock_thread_class.return_value = mock_thread

        def _docker_launcher(max_proc=None):
            config = config_factory(max_proc)
            return Docker(config)

        yield _docker_launcher


@pytest.fixture
def mock_project():
    project = Mock()
    project.id.return_value = 'test_project'
    project.repository.return_value = 'test_repo'
    project.resources.return_value = {}
    return project


@pytest.mark.parametrize("max_proc,expected_thread_alive", [
    (2, True),
    (None, False)
])
def test_docker_init(docker_launcher_factory, max_proc, expected_thread_alive):
    """Test Docker initialization with and without max_proc setting"""
    docker_launcher = docker_launcher_factory(max_proc)

    assert docker_launcher.max_proc == max_proc
    if expected_thread_alive:
        assert docker_launcher._thread is not None
        assert docker_launcher._thread.is_alive()
    else:
        assert docker_launcher._thread is None


@pytest.mark.parametrize("running_jobs,max_proc,should_start_immediately", [
    (1, 2, True),  # We have capacity to start immediately
    (2, 2, False),  # At capacity, shouldn't start immediately
    (0, None, True)  # No max_proc, should start immediately
])
def test_schedule(docker_launcher_factory, mock_docker_client, mock_project,
                  running_jobs, max_proc, should_start_immediately):
    """Test scheduling behavior with different capacity configurations"""
    docker_launcher = docker_launcher_factory(max_proc)

    # Mock methods if needed
    if max_proc is not None:
        docker_launcher.get_running_jobs_count = Mock(return_value=running_jobs)
        docker_launcher.start_pending_containers = Mock()

    # Mock container creation
    mock_container = Mock()
    mock_docker_client.containers.create.return_value = mock_container

    # Prepare parameters for schedule
    version = 'v1'
    spider = 'test_spider'
    job_id = f'job_{running_jobs}_{max_proc}'
    settings = {}
    args = {}

    # Patch the logger to check log outputs
    with patch('scrapyd_k8s.launcher.docker.logger') as mock_logger:
        # Call schedule
        docker_launcher.schedule(mock_project, version, spider, job_id, settings, args)

        # Verify that container is created
        mock_docker_client.containers.create.assert_called_once()

        if max_proc is None:
            # If max_proc is not set, container.start() should be called immediately
            mock_container.start.assert_called_once()
        elif should_start_immediately:
            # We have capacity, start_pending_containers should be called
            docker_launcher.start_pending_containers.assert_called_once()
        else:
            # At capacity, start_pending_containers should not be called
            docker_launcher.start_pending_containers.assert_not_called()
            # Verify that container.start() is not called immediately
            mock_container.start.assert_not_called()
            # Check that the correct log message was output
            mock_logger.info.assert_called_with(f"Job {job_id} is pending due to max_proc limit.")


def test_get_running_jobs_count(docker_launcher_factory, mock_docker_client):
    """Test counting of running jobs"""
    docker_launcher = docker_launcher_factory(2)

    # Test with different numbers of containers
    for num_containers in [0, 1, 3]:
        # Reset mocks
        mock_docker_client.reset_mock()

        # Mock the list of running containers
        mock_container_list = [Mock() for _ in range(num_containers)]
        mock_docker_client.containers.list.return_value = mock_container_list

        count = docker_launcher.get_running_jobs_count()

        # Verify that the count matches the number of mock containers
        assert count == num_containers
        mock_docker_client.containers.list.assert_called_with(
            filters={'label': docker_launcher.LABEL_PROJECT, 'status': 'running'})


def test_start_pending_containers(docker_launcher_factory, mock_docker_client):
    """Test starting of pending containers"""
    docker_launcher = docker_launcher_factory(2)

    # Create a mock method for get_next_pending_container instead of relying on sorting
    def mock_get_next_pending_container():
        if docker_launcher.get_running_jobs_count() < docker_launcher.max_proc:
            return mock_pending_containers[0] if mock_pending_containers else None
        return None

    docker_launcher.get_next_pending_container = Mock(side_effect=mock_get_next_pending_container)

    # Test different scenarios
    test_cases = [
        # (running_count, pending_containers_count, can_start_more)
        (0, 2, True),  # Can start, have pending containers
        (1, 2, True),  # Can start, have pending containers
        (2, 2, False),  # At capacity, can't start any
        (1, 0, False),  # Can start, but no pending containers
    ]

    for running_count, pending_count, should_start in test_cases:
        # Reset mocks
        mock_docker_client.reset_mock()
        docker_launcher.get_running_jobs_count = Mock(
            side_effect=[running_count, running_count + 1] if should_start else [running_count])

        # Mock pending containers
        mock_pending_containers = [Mock() for _ in range(pending_count)]
        for i, container in enumerate(mock_pending_containers):
            container.name = f'pending_container_{i}'

        # Patch logger to check log outputs
        with patch('scrapyd_k8s.launcher.docker.logger') as mock_logger:
            # Call start_pending_containers
            docker_launcher.start_pending_containers()

            if should_start:
                # Verify that the container.start method was called
                mock_pending_containers[0].start.assert_called_once()

                # Verify that the correct log message was output
                expected_running = running_count + 1
                mock_logger.info.assert_called_with(
                    f"Started pending container {mock_pending_containers[0].name}. "
                    f"Total running jobs now: {expected_running}"
                )
            else:
                # If no container should be started, ensure that no start methods were called
                if pending_count > 0:
                    mock_pending_containers[0].start.assert_not_called()

def test_background_task():
    """Test the background task directly"""
    # Create a config mock
    config = Mock()
    config.scrapyd.return_value.get.return_value = '2'  # max_proc set to 2

    # Mock the Docker class
    with patch.object(Docker, '__init__', return_value=None), \
            patch.object(Docker, 'start_pending_containers') as mock_start_pending:
        # Create Docker instance and directly call the background task method
        docker_launcher = Docker(config)
        docker_launcher.check_interval = 0.1  # Set a short interval for testing

        # Manually set the run flag
        docker_launcher._run = True

        # Call the method directly without threading
        # We'll call it just once without the loop for testing
        docker_launcher._background_task()

        # Verify start_pending_containers was called
        mock_start_pending.assert_called_once()
