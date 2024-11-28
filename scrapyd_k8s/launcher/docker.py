import logging
import re
import socket

import threading
import time

import docker
from ..utils import format_iso_date_string, native_stringify_dict

logger = logging.getLogger(__name__)

class Docker:

    LABEL_PROJECT = 'org.scrapy.project'
    LABEL_SPIDER = 'org.scrapy.spider'
    LABEL_JOB_ID = 'org.scrapy.job_id'

    # translates status to scrapyd terminology
    STATUS_MAP = {
        'created': 'pending',
        'scheduled': 'pending',
        'exited': 'finished'
    }

    def __init__(self, config):
        self._docker = docker.from_env()
        self.max_proc = config.scrapyd().get('max_proc')
        if self.max_proc is not None:
            self.max_proc = int(self.max_proc)
            self._stop_event = threading.Event()
            self._lock = threading.Lock()

            self._thread = threading.Thread(target=self._background_task, daemon=True)
            self._thread.start()
            logger.info("Background thread for managing Docker containers started.")
        else:
            self._thread = None
            logger.info("Job limit not set; Docker launcher will not limit running jobs.")

    def _background_task(self):
        """
        Background thread that periodically checks and starts pending containers.
        """
        check_interval = 5  # seconds
        while not self._stop_event.is_set():
            with self._lock:
                self.start_pending_containers()
            time.sleep(check_interval)

    def shutdown(self):
        """
        Cleanly shutdown the background thread.
        """
        if self._thread is not None:
            self._stop_event.set()
            self._thread.join()
            logger.info("Background thread for managing Docker containers stopped.")

    def get_node_name(self):
        return socket.gethostname()

    def listjobs(self, project_id=None):
        label = self.LABEL_PROJECT + ('=%s'%(project_id) if project_id else '')
        jobs = self._docker.containers.list(all=True, filters={ 'label': label })
        jobs = [self._parse_job(j) for j in jobs]
        return jobs

    def schedule(self, project, version, spider, job_id, settings, args):
        _settings = [i for k, v in native_stringify_dict(settings, keys_only=False).items() for i in ['-s', f"{k}={v}"]]
        _args = [i for k, v in native_stringify_dict(args, keys_only=False).items() for i in ['-a', f"{k}={v}"]]
        env = {
            'SCRAPY_PROJECT': project.id(),
            'SCRAPYD_SPIDER': spider,
            'SCRAPYD_JOB': job_id,
        } # TODO env_source handling
        resources = project.resources(spider)
        c = self._docker.containers.create(
            image=project.repository() + ':' + version,
            command=['scrapy', 'crawl', spider, *_args, *_settings],
            environment=env,
            labels={
                self.LABEL_PROJECT: project.id(),
                self.LABEL_SPIDER: spider,
                self.LABEL_JOB_ID: job_id,
            },
            name='_'.join(['scrapyd', project.id(), job_id]),
            detach=True,
            mem_limit=resources.get('limits', {}).get('memory'),
            cpu_quota=_str_to_micro(resources.get('limits', {}).get('cpu'))
        )
        if self.max_proc is not None:
            running_jobs_count = self.get_running_jobs_count()
            if running_jobs_count < self.max_proc:
                self.start_pending_containers()
            else:
                logger.info(f"Job {job_id} is pending due to max_proc limit.")
        else:
            c.start()
            logger.info(f"Job {job_id} started without suspension.")

    def start_pending_containers(self):
        """
        Checks if there is capacity to start pending containers and starts them if possible.
        """
        running_jobs_count = self.get_running_jobs_count()
        logger.debug(f"Current running jobs: {running_jobs_count}, max_proc: {self.max_proc}")

        while running_jobs_count < self.max_proc:
            pending_container = self.get_next_pending_container()
            if not pending_container:
                logger.info("No pending containers to start.")
                break
            try:
                pending_container.start()
                running_jobs_count += 1
                logger.info(
                    f"Started pending container {pending_container.name}. Total running jobs now: {running_jobs_count}")
            except Exception as e:
                logger.error(f"Failed to start container {pending_container.name}: {e}")
                break

    def get_next_pending_container(self):
        pending_containers = self._docker.containers.list(all=True, filters={
            'label': self.LABEL_PROJECT,
            'status': 'created',
        })
        if not pending_containers:
            return None
        # Sort by creation time to ensure FIFO order
        pending_containers.sort(key=lambda c: c.attrs['Created'])
        return pending_containers[0]

    def cancel(self, project_id, job_id, signal):
        c = self._get_container(project_id, job_id)
        if not c:
            return None

        prevstate = self._docker_to_scrapyd_status(c.status)
        if c.status == 'created' or c.status == 'scheduled':
            c.remove()
            logger.info(f"Removed pending container {c.name}.")
        elif c.status == 'running':
            c.kill(signal='SIG' + signal)
            logger.info(f"Killed and removed running container {c.name}.")
        # After cancelling, try to start pending containers since we might have capacity
        if self.max_proc is not None:
            self.start_pending_containers()
        return prevstate

    def enable_joblogs(self, config, resource_watcher):
        logger.warning("Job logs are not supported when using the Docker launcher.")

    def get_running_jobs_count(self):
        if self.max_proc is not None:
            # Return the number of running Docker containers matching the job labels
            label = self.LABEL_PROJECT
            running_jobs = self._docker.containers.list(filters={'label': label, 'status': 'running'})
            return len(running_jobs)
        else:
            # If job limiting is not enabled, return 0 to avoid unnecessary processing
            return 0

    def _parse_job(self, c):
        state = self._docker_to_scrapyd_status(c.status)
        return {
            'id': c.labels.get(self.LABEL_JOB_ID),
            'state': state,
            'project': c.labels.get(self.LABEL_PROJECT),
            'spider': c.labels.get(self.LABEL_SPIDER),
            'start_time': format_iso_date_string(c.attrs['State']['StartedAt']) if state in ['running', 'finished'] else None,
            'end_time': None,  # Not available using Docker's API. Add to the job representation to keep it the same as K8s jobs listing.
        }

    def _get_container(self, project_id, job_id):
        filters = { 'label': self.LABEL_JOB_ID + '=' + job_id }
        c = self._docker.containers.list(all=True, filters=filters)
        if not c:
            return None
        c = c[0]

        if c.labels.get(self.LABEL_PROJECT) != project_id:
            return None

        return c

    def _docker_to_scrapyd_status(self, status):
        return self.STATUS_MAP.get(status, status)

def _str_to_micro(s):
    """Convert str to micro, so 1 -> 1000000, 0.1m -> 100, etc."""
    if s is None: return
    if isinstance(s, int):
        return s * 1_000_000
    if isinstance(s, str):
        if re.match(r'^[0-9.]+$', s): return int(float(s) * 1_000_000)
        if re.match(r'^[0-9.]+m$', s): return int(float(s[0:-1]) * 1_000)
    raise Exception('Unrecognized number format: ' + str(s))
