import os
import threading
import tempfile
import logging

from kubernetes import client, watch
from .object_storage import LibcloudObjectStorage

logger = logging.getLogger(__name__)

watcher_threads = {}
pod_tmp_mapping = {}

def get_last_n_lines(file_path, num_lines):
    """Efficiently retrieve the last `num_lines` lines from `file_path`."""
    try:
        with open(file_path, 'rb') as f:
            # Move to the end of the file
            f.seek(0, os.SEEK_END)
            file_size = f.tell()
            block_size = 6144
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
            print("LINES FOUND", result)
            return result
    except FileNotFoundError:
        logger.warning(f"File not found: {file_path}")
        return []

def concatenate_and_delete_files(main_file_path, temp_file_path):
    try:
        with open(main_file_path, 'a') as main_file, open(temp_file_path, 'r') as temp_file:
            main_file.write(temp_file.read())
        os.remove(temp_file_path)
        logger.info(f"Concatenated '{temp_file_path}' into '{main_file_path}' and deleted temporary file.")
    except Exception as e:
        logger.exception(f"Error concatenating files '{main_file_path}' and '{temp_file_path}': {e}")

def make_log_filename_for_job(job_name):
    if pod_tmp_mapping.get(job_name) is not None:
        return pod_tmp_mapping[job_name]
    else:
        temp_dir = tempfile.gettempdir()
        app_temp_dir = os.path.join(temp_dir, 'job_logs')
        os.makedirs(app_temp_dir, exist_ok=True)
        fd, path = tempfile.mkstemp(prefix=f"{job_name}_logs_", suffix=".txt", dir=app_temp_dir)
        os.close(fd)
        pod_tmp_mapping[job_name] = path
        return path

def stream_logs(job_name, namespace, num_lines_to_check):
    log_lines_counter = 0
    v1 = client.CoreV1Api()
    w = watch.Watch()
    log_file_path = make_log_filename_for_job(job_name)
    last_n_lines = get_last_n_lines(log_file_path, num_lines_to_check)
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
                    namespace=namespace,
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
                concatenate_and_delete_files(log_file_path, temp_file_path)
            else:
                os.remove(temp_file_path)
                logger.info(f"Removed temporary file '{temp_file_path}' after streaming logs for job '{job_name}'.")
    except Exception as e:
        logger.exception(f"Error streaming logs for job '{job_name}': {e}")

def watch_pods(config):
    object_storage_provider = LibcloudObjectStorage(config)
    namespace = config.get_namespace()

    num_lines_to_check = int(config.joblogs().get('num_lines_to_check'))
    w = watch.Watch()
    v1 = client.CoreV1Api()
    try:
        for event in w.stream(v1.list_namespaced_pod, namespace=namespace):
            pod = event['object']
            # check the labels in the docs
            if pod.status.phase == 'Running' and pod.metadata.labels.get("org.scrapy.job_id"):
                thread_name = "%s_%s" % (namespace, pod.metadata.name)
                if (thread_name in watcher_threads
                        and watcher_threads[thread_name] is not None
                        and watcher_threads[thread_name].is_alive()):
                    pass
                else:
                    watcher_threads[thread_name] = threading.Thread(
                        target=stream_logs,
                        kwargs={
                            'job_name': pod.metadata.name,
                            'namespace': namespace,
                            'num_lines_to_check': num_lines_to_check
                        }
                    )
                    watcher_threads[thread_name].start()
            elif (pod.status.phase == 'Succeeded' or pod.status.phase == 'Failed') and pod.metadata.labels.get("org.scrapy.job_id"):
                log_filename = pod_tmp_mapping.get(pod.metadata.name)
                if log_filename is not None and os.path.isfile(log_filename) and os.path.getsize(log_filename) > 0:
                    if object_storage_provider.is_local_file_uploaded(log_filename):
                        logger.info("File already exists")
                    else:
                        object_storage_provider.upload_file(log_filename)
                else:
                    logger.info("Logfile not found %s", pod.metadata.name)
            else:
                print("other type " + event["type"] + " " + pod.metadata.name + " - " + pod.status.phase)
    except Exception as e:
        logger.exception(f"Error watching pods in namespace '{namespace}': {e}")

def joblogs_init(config):
    joblogs_config = config.joblogs()
    if joblogs_config.get('storage_provider') is not None:
        pod_watcher_thread = threading.Thread(
            target=watch_pods,
            kwargs={'config': config}
        )
        pod_watcher_thread.daemon = True  # Optional: make thread a daemon
        pod_watcher_thread.start()
        logger.info("Started pod watcher thread for job logs.")
    else:
        logger.warning("No storage provider configured; job logs will not be uploaded.")
