import logging
import datetime

from kubernetes.client import ApiException

logger = logging.getLogger(__name__)

class KubernetesScheduler:
    """
    Manages scheduling of Kubernetes jobs to limit the number of concurrently running jobs.
    """

    def __init__(self, config, launcher, max_proc):
        """
        Initializes the KubernetesScheduler.

        Parameters
        ----------
        config : Config
            The configuration object.
        launcher : K8s
            The launcher instance with initialized Kubernetes clients.
        max_proc : int
            Maximum number of concurrent jobs.

        Raises
        ------
        TypeError
            If `max_proc` is not an integer.
        """
        try:
            self.config = config
            self.launcher = launcher
            if not isinstance(max_proc, int):
                raise TypeError(f"max_proc must be an integer, got {type(max_proc).__name__}")
            self.max_proc = max_proc
            self.namespace = config.namespace()
        except TypeError as e:
            logger.exception(f"TypeError during KubernetesScheduler initialization: {e}")
            raise

    def handle_pod_event(self, event):
        """
        Handles pod events from the ResourceWatcher.

        Processes events related to pod lifecycle changes. If a pod associated with a job
        has terminated (either succeeded or failed), it triggers the scheduler to check
        and potentially unsuspend other suspended jobs to utilize available capacity.

        Parameters
        ----------
        event : dict
            A dictionary representing the pod event received from Kubernetes.

        Notes
        -----
        This method handles and logs the following exceptions internally:
        - KeyError: If the event dictionary lacks the 'object' or 'type' keys.
        - AttributeError: If the pod object lacks attributes like `status.phase` or `metadata.name`.
        - TypeError: If `event` is not a dictionary or does not have the expected structure.

        Exceptions are not propagated further.
        """
        try:
            if not isinstance(event, dict):
                raise TypeError(f"Event must be a dictionary, got {type(event).__name__}")
            pod = event['object']
            pod_phase = pod.status.phase
            pod_name = pod.metadata.name
            event_type = event['type']

            if not hasattr(pod, 'status') or not hasattr(pod.status, 'phase'):
                raise AttributeError("Pod object missing 'status.phase' attribute")
            if not hasattr(pod, 'metadata') or not hasattr(pod.metadata, 'name'):
                raise AttributeError("Pod object missing 'metadata.name' attribute")

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
        except KeyError as e:
            logger.error(f"KeyError in handle_pod_event: Missing key {e} in event: {event}")
        except AttributeError as e:
            logger.error(f"AttributeError in handle_pod_event: {e} in event: {event}")
        except TypeError as e:
            logger.error(f"TypeError in handle_pod_event: {e} in event: {event}")

    def check_and_unsuspend_jobs(self):
        """
        Checks if there is capacity to unsuspend jobs and unsuspends them if possible.

        Continuously unsuspends suspended jobs until the number of running jobs reaches
        the maximum allowed (`max_proc`) or there are no more suspended jobs available.

        Notes
        -----
        This method handles and logs the following exceptions internally:
        - ApiException: If there are issues interacting with the Kubernetes API during job count retrieval
          or while unsuspending a job.
        - AttributeError: If the launcher object lacks required methods.
        - TypeError: If `max_proc` is not an integer.

        Exceptions are not propagated further.
        """
        try:
            running_jobs_count = self.launcher.get_running_jobs_count()
            logger.debug(f"Current running jobs: {running_jobs_count}, max_proc: {self.max_proc}")

            while running_jobs_count < self.max_proc:
                job_id = self.get_next_suspended_job_id()
                if not job_id:
                    logger.info("No suspended jobs to unsuspend.")
                    break
                try:
                    success = self.launcher.unsuspend_job(job_id)
                    if success:
                        running_jobs_count += 1
                        logger.info(f"Unsuspended job {job_id}. Total running jobs now: {running_jobs_count}")
                    else:
                        logger.error(f"Failed to unsuspend job {job_id}")
                        break
                except ApiException as e:
                    logger.error(f"Kubernetes API exception while unsuspending job {job_id}: {e}")
                    break
                except AttributeError as e:
                    logger.error(f"AttributeError while unsuspending job {job_id}: {e}")
                    break
        except ApiException as e:
            logger.error(f"Kubernetes API exception in check_and_unsuspend_jobs: {e}")
        except AttributeError as e:
            logger.error(f"AttributeError in check_and_unsuspend_jobs: {e}")
        except TypeError as e:
            logger.error(f"TypeError in check_and_unsuspend_jobs: {e}")

    def get_next_suspended_job_id(self):
        """
        Retrieves the ID of the next suspended job from Kubernetes,
        sorting by creation timestamp to ensure FIFO order.

        Returns
        -------
        str or None
            The job ID of the next suspended job, or None if none are found.

        Notes
        -----
        This method handles and logs the following exceptions internally:
        - ApiException: If there are issues interacting with the Kubernetes API during job retrieval.
        - AttributeError: If job objects lack `metadata.creation_timestamp` or `metadata.labels`.
        - TypeError: If the returned jobs list is not a list.

        Exceptions are not propagated further.
        """
        try:
            label_selector = f"{self.launcher.LABEL_JOB_ID}"
            jobs = self.launcher.list_suspended_jobs(label_selector=label_selector)

            if not isinstance(jobs, list):
                raise TypeError(f"list_suspended_jobs should return a list, got {type(jobs).__name__}")

            if not jobs:
                logger.debug("No suspended jobs found.")
                return None

            # Assign default timestamp to jobs missing creation_timestamp
            for job in jobs:
                if not hasattr(job, 'metadata') or not hasattr(job.metadata, 'creation_timestamp') or not job.metadata.creation_timestamp:
                    job.metadata.creation_timestamp = datetime.datetime.max
                    logger.warning(
                        f"Job {job} missing 'metadata.creation_timestamp'; assigned max timestamp.")

            # Sort jobs by creation timestamp to ensure FIFO order
            jobs.sort(key=lambda job: job.metadata.creation_timestamp)
            job = jobs[0]
            if not hasattr(job.metadata, 'labels'):
                raise AttributeError(f"Job object missing 'metadata.labels': {job}")
            job_id = job.metadata.labels.get(self.launcher.LABEL_JOB_ID)
            logger.debug(f"Next suspended job to unsuspend: {job_id}")
            return job_id
        except ApiException as api_e:
            logger.error(f"Kubernetes API exception in get_next_suspended_job_id: {api_e}")
        except AttributeError as attr_e:
            logger.error(f"AttributeError in get_next_suspended_job_id: {attr_e}")
        except TypeError as type_e:
            logger.error(f"TypeError in get_next_suspended_job_id: {type_e}")
