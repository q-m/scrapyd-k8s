import os
from kubernetes import client, watch
import subprocess

def get_last_n_lines(file_path, num_lines_to_check):
    lines = []
    try:
        with open(file_path, 'r') as file:
            lines = file.readlines()
        return lines[-num_lines_to_check:]
    except FileNotFoundError:
        return []

def concatenate_and_delete_files(main_file_path, temp_file_path):
    try:
        subprocess.run(f"cat {temp_file_path} >> {main_file_path}", shell=True, check=True)
        os.remove(temp_file_path)
    except Exception as e:
        print(f"CONCATENATION ERROR: {e}")

def make_log_filename_for_job(job_name):
    return os.path.join('/tmp', f"{job_name}_logs.txt")

def stream_logs(job_name, namespace, num_lines_to_check):
    log_lines_counter: int = 0
    v1 = client.CoreV1Api()
    w = watch.Watch()
    log_file_path = make_log_filename_for_job(job_name)
    last_n_lines = get_last_n_lines(log_file_path, num_lines_to_check)
    if len(last_n_lines) == 0:
        print("file is empty, writing logs")

    with open(log_file_path, 'a') as log_file:
        # check if file is created
        # if it exists, read the last n lines and find that spot into the file
        # append to the file only the logs after those two lines
        temp_file = os.path.join('/tmp', f"{job_name}_logs_tmp.txt")
        with open(temp_file, 'a') as temp_logs:
            for e in w.stream(v1.read_namespaced_pod_log, name=job_name, namespace=namespace, follow=True, _preload_content=False):
                temp_logs.write(e + "\n")
                temp_logs.flush()

                if log_lines_counter == len(last_n_lines):
                    log_file.write(e + "\n")
                    log_file.flush()
                elif e + "\n" == last_n_lines[log_lines_counter]:
                    log_lines_counter += 1
                else:
                    log_lines_counter = 0

        if len(last_n_lines) > log_lines_counter:
            concatenate_and_delete_files(log_file_path, temp_file)

        os.remove(temp_file)
