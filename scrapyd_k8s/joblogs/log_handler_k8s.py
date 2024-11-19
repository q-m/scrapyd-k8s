import os
import threading
import tempfile
import logging

from kubernetes import client, watch
from scrapyd_k8s.object_storage import LibcloudObjectStorage

logger = logging.getLogger(__name__)

class KubernetesJobLogHandler:
    """
    A class to handle Kubernetes job logs by watching pods, streaming logs, and uploading them to object storage.

    ...

    Attributes
    ----------
    DEFAULT_BLOCK_SIZE : int
        Default size (in bytes) of blocks to read when retrieving the last N lines from a file.
    config : object
        Configuration object containing settings for job logs and storage.
    watcher_threads : dict
        Dictionary to keep track of watcher threads for each pod.
    pod_tmp_mapping : dict
        Mapping of pod names to their temporary log file paths.
    namespace : str
        Kubernetes namespace to watch pods in.
    num_lines_to_check : int
        Number of lines to check for matching logs when resuming log streaming.
    object_storage_provider : LibcloudObjectStorage
        Instance of the object storage provider for uploading logs.

    Methods
    -------
    start():
        Starts the pod watcher thread for job logs.
    get_last_n_lines(file_path, num_lines):
        Efficiently retrieves the last `num_lines` lines from a file.
    concatenate_and_delete_files(main_file_path, temp_file_path, block_size=6144):
        Concatenates a temporary file to the main log file and deletes the temporary file.
    make_log_filename_for_job(job_name):
        Generates a unique temporary file path for storing logs of a job.
    stream_logs(job_name):
        Streams logs from a Kubernetes pod and writes them to a file.
    watch_pods():
        Watches Kubernetes pods and handles events such as starting log streaming or uploading logs.
    """
    # The value was chosen to provide a balance between memory usage and the number of I/O operations
    DEFAULT_BLOCK_SIZE = 6144

    def __init__(self, config):
        """
        Constructs all the necessary attributes for the KubernetesJobLogHandler object.

        Parameters
        ----------
        config : object
            Configuration object containing settings for job logs and storage.
        """
        self.config = config
        self.watcher_threads = {}
        self.pod_tmp_mapping = {}
        self.namespace = config.namespace()
        self.num_lines_to_check = int(config.joblogs().get('num_lines_to_check', 0))
        self.object_storage_provider = LibcloudObjectStorage(self.config)

    def get_last_n_lines(self, file_path, num_lines):
        """
        Efficiently retrieves the last `num_lines` lines from a file.

        Parameters
        ----------
        file_path : str
            Path to the file from which to read the last lines.
        num_lines : int
            Number of lines to retrieve from the end of the file.

        Returns
        -------
        list of str
            A list containing the last `num_lines` lines from the file.
        """
        try:
            with open(file_path, 'rb') as f:
                # Move to the end of the file
                f.seek(0, os.SEEK_END)
                file_size = f.tell()
                block_size = self.DEFAULT_BLOCK_SIZE
                data = b''
                remaining_lines = num_lines
                while remaining_lines > 0 and file_size > 0:
                    if file_size - block_size > 0:
                        f.seek(file_size - block_size)
                        block_data = f.read(block_size)
                    else:
                        f.seek(0)
                        block_data = f.read(file_size)
                    file_size -= block_size
                    data = block_data + data
                    lines_found = data.count(b'\n')
                    # If we've found enough lines, we can stop reading more blocks
                    if lines_found >= remaining_lines:
                        break

                # Decode the data and split into lines
                lines = data.decode('utf-8', errors='replace').splitlines()
                # Return the last `num_lines`
                result = lines[-num_lines:]
                return result
        except FileNotFoundError:
            logger.warning(f"File not found: {file_path}")
            return []

    def concatenate_and_delete_files(self, main_file_path, temp_file_path, block_size=DEFAULT_BLOCK_SIZE):
        """
        Concatenates a temporary file to the main log file and deletes the temporary file.

        Parameters
        ----------
        main_file_path : str
            Path to the main log file.
        temp_file_path : str
            Path to the temporary log file to be concatenated.
        block_size : int, optional
            Size of blocks to read at a time (default is 6144 bytes).

        Returns
        -------
        None
        """
        try:
            with open(main_file_path, 'ab') as main_file, open(temp_file_path, 'rb') as temp_file:
                while True:
                    block_data = temp_file.read(block_size)
                    if not block_data:
                        break
                    main_file.write(block_data)
            os.remove(temp_file_path)
            logger.debug(f"Concatenated '{temp_file_path}' into '{main_file_path}' and deleted temporary file.")
        except (IOError, OSError) as e:
            logger.error(f"Failed to concatenate and delete files for job: {e}")

    def make_log_filename_for_job(self, job_name):
        """
        Generates a unique temporary file path for storing logs of a job.

        Parameters
        ----------
        job_name : str
            Name of the Kubernetes job or pod.

        Returns
        -------
        str
            Path to the temporary log file for the given job.
        """
        if self.pod_tmp_mapping.get(job_name) is not None:
            return self.pod_tmp_mapping[job_name]
        temp_dir = tempfile.gettempdir()
        app_temp_dir = os.path.join(temp_dir, 'job_logs')
        os.makedirs(app_temp_dir, exist_ok=True)
        fd, path = tempfile.mkstemp(prefix=f"{job_name}_logs_", suffix=".txt", dir=app_temp_dir)
        os.close(fd)
        self.pod_tmp_mapping[job_name] = path
        return path

    def stream_logs(self, job_name):
        """
        Streams logs from a Kubernetes pod and writes them to a file.

        Parameters
        ----------
        job_name : str
            Name of the Kubernetes pod to stream logs from.

        Returns
        -------
        None
        """
        log_lines_counter = 0
        v1 = client.CoreV1Api()
        w = watch.Watch()
        log_file_path = self.make_log_filename_for_job(job_name)
        last_n_lines = self.get_last_n_lines(log_file_path, self.num_lines_to_check)
        if len(last_n_lines) == 0:
            logger.info(f"Log file '{log_file_path}' is empty or not found. Starting fresh logs for job '{job_name}'.")

        try:
            with open(log_file_path, 'a') as log_file:
                temp_dir = os.path.dirname(log_file_path)
                with tempfile.NamedTemporaryFile(mode='w+', delete=False, dir=temp_dir,
                                                 prefix=f"{job_name}_logs_tmp_", suffix=".txt") as temp_logs:
                    temp_file_path = temp_logs.name
                    for line in w.stream(
                        v1.read_namespaced_pod_log,
                        name=job_name,
                        namespace=self.namespace,
                        follow=True,
                        _preload_content=False
                    ):
                        temp_logs.write(line + "\n")
                        temp_logs.flush()

                        if log_lines_counter == len(last_n_lines):
                            log_file.write(line + "\n")
                            log_file.flush()
                        elif line == last_n_lines[log_lines_counter]:
                            log_lines_counter += 1
                        else:
                            log_lines_counter = 0

                if len(last_n_lines) > log_lines_counter:
                    self.concatenate_and_delete_files(log_file_path, temp_file_path)
                else:
                    os.remove(temp_file_path)
                    logger.info(f"Removed temporary file '{temp_file_path}' after streaming logs for job '{job_name}'.")
        except Exception as e:
            logger.exception(f"Error streaming logs for job '{job_name}': {e}")

    def handle_events(self, event):
        """
        Watches Kubernetes pods and handles events such as starting log streaming or uploading logs.

        Returns
        -------
        None
        """
        self.object_storage_provider = LibcloudObjectStorage(self.config)
        try:

            pod = event['object']
            if pod.metadata.labels.get("org.scrapy.job_id"):
                job_id = pod.metadata.labels.get("org.scrapy.job_id")
                pod_name = pod.metadata.name
                thread_name = f"{self.namespace}_{pod_name}"
                if pod.status.phase == 'Running':
                    if (thread_name in self.watcher_threads
                            and self.watcher_threads[thread_name] is not None
                            and self.watcher_threads[thread_name].is_alive()):
                        pass
                    else:
                        self.watcher_threads[thread_name] = threading.Thread(
                            target=self.stream_logs,
                            args=(pod_name,)
                        )
                        self.watcher_threads[thread_name].start()
                elif pod.status.phase in ['Succeeded', 'Failed']:
                    log_filename = self.pod_tmp_mapping.get(pod_name)
                    if log_filename is not None and os.path.isfile(log_filename) and os.path.getsize(log_filename) > 0:
                        if self.object_storage_provider.object_exists(job_id):
                            logger.info(f"Log file for job '{job_id}' already exists in storage.")
                        else:
                            self.object_storage_provider.upload_file(log_filename)
                    else:
                        logger.info(f"Logfile not found for job '{job_id}'")
            else:
                logger.debug(f"Other pod event type '{event['type']}' for pod '{pod.metadata.name}' - Phase: '{pod.status.phase}'")
        except Exception as e:
            logger.exception(f"Error watching pods in namespace '{self.namespace}': {e}")
