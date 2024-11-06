import logging

logger = logging.getLogger(__name__)

class KubernetesScheduler:
    """
    Manages scheduling of Kubernetes jobs to limit the number of concurrently running jobs.
    """

    def __init__(self, config, launcher, resource_watcher, max_proc):
        """
        Initializes the KubernetesScheduler.

        Parameters
        ----------
        config : Config
            The configuration object.
        launcher : K8s
            The launcher instance with initialized Kubernetes clients.
        resource_watcher : ResourceWatcher
            The resource watcher to subscribe to pod events.
        max_proc : int
            Maximum number of concurrent jobs.
        """
        self.config = config
        self.launcher = launcher
        self.max_proc = max_proc
        self.namespace = config.scrapyd().get('namespace', 'default')

        # Subscribe to the ResourceWatcher
        resource_watcher.subscribe(self.handle_pod_event)
        logger.info(f"KubernetesScheduler initialized with max_proc={self.max_proc}.")

    def handle_pod_event(self, event: dict):
        """
        Handles pod events from the ResourceWatcher.
        """
        pod = event['object']
        pod_phase = pod.status.phase
        pod_name = pod.metadata.name
        event_type = event['type']

        logger.debug(f"KubernetesScheduler received event: {event_type}, pod: {pod_name}, phase: {pod_phase}")

        # Check if this pod is related to our jobs
        if not pod.metadata.labels.get(self.launcher.LABEL_JOB_ID):
            logger.debug(f"Pod {pod_name} does not have our job label; ignoring.")
            return

        # If a pod has terminated (Succeeded or Failed), we may have capacity to unsuspend jobs
        if pod_phase in ('Succeeded', 'Failed') and event_type in ('MODIFIED', 'DELETED'):
            logger.info(f"Pod {pod_name} has completed with phase {pod_phase}. Checking for suspended jobs.")
            self.check_and_unsuspend_jobs()
        else:
            logger.debug(f"Pod {pod_name} event not relevant for unsuspension.")

    def check_and_unsuspend_jobs(self):
        """
        Checks if there is capacity to unsuspend jobs and unsuspends them if possible.
        """
        running_jobs_count = self.launcher.get_running_jobs_count()
        logger.debug(f"Current running jobs: {running_jobs_count}, max_proc: {self.max_proc}")

        while running_jobs_count < self.max_proc:
            job_id = self.get_next_suspended_job_id()
            if not job_id:
                logger.info("No suspended jobs to unsuspend.")
                break
            success = self.launcher.unsuspend_job(job_id)
            if success:
                running_jobs_count += 1
                logger.info(f"Unsuspended job {job_id}. Total running jobs now: {running_jobs_count}")
            else:
                logger.error(f"Failed to unsuspend job {job_id}")
                break

    def get_next_suspended_job_id(self):
        """
        Retrieves the ID of the next suspended job from Kubernetes,
        sorting by creation timestamp to ensure FIFO order.

        Returns
        -------
        str or None
            The job ID of the next suspended job, or None if none are found.
        """
        label_selector = f"{self.launcher.LABEL_JOB_ID}"
        jobs = self.launcher.list_suspended_jobs(label_selector=label_selector)
        if not jobs:
            logger.debug("No suspended jobs found.")
            return None
        # Sort jobs by creation timestamp to ensure FIFO order
        jobs.sort(key=lambda job: job.metadata.creation_timestamp)
        job = jobs[0]
        job_id = job.metadata.labels.get(self.launcher.LABEL_JOB_ID)
        logger.debug(f"Next suspended job to unsuspend: {job_id}")
        return job_id
