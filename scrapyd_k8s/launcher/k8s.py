import os
import logging

import kubernetes
import kubernetes.stream
import logging
from signal import Signals

from ..k8s_resource_watcher import ResourceWatcher
from ..utils import format_datetime_object, native_stringify_dict
from scrapyd_k8s.joblogs import KubernetesJobLogHandler

logger = logging.getLogger(__name__)

logger = logging.getLogger(__name__)

class K8s:

    LABEL_PROJECT = 'org.scrapy.project'
    LABEL_SPIDER = 'org.scrapy.spider'
    LABEL_JOB_ID = 'org.scrapy.job_id'

    def __init__(self, config):
        self._namespace = config.scrapyd().get('namespace', 'default')
        self._pull_secret = config.scrapyd().get('pull_secret')
        # TODO figure out where to put Kubernetes initialisation
        try:
            kubernetes.config.load_incluster_config()
        except kubernetes.config.config_exception.ConfigException:
            kubernetes.config.load_kube_config()

        self._k8s = kubernetes.client.CoreV1Api()
        self._k8s_batch = kubernetes.client.BatchV1Api()

        self._init_resource_watcher(config)

    def _init_resource_watcher(self, config):
        self.resource_watcher = ResourceWatcher(self._namespace, config)

        if config.joblogs() is not None:
            self.enable_joblogs(config)
        else:
            logger.debug("Job logs handling not enabled; 'joblogs' configuration section is missing.")

    def get_node_name(self):
        deployment = os.getenv('MY_DEPLOYMENT_NAME', 'default')
        namespace = os.getenv('MY_NAMESPACE')
        return ".".join([n for n in [namespace, deployment] if n])

    def listjobs(self, project=None):
        label = self.LABEL_PROJECT + ('=%s'%(project) if project else '')
        jobs = self._k8s_batch.list_namespaced_job(namespace=self._namespace, label_selector=label)
        jobs = [self._parse_job(j) for j in jobs.items]
        return jobs

    def schedule(self, project, version, spider, job_id, settings, args, start_suspended=False):
        job_name = self._k8s_job_name(project.id(), job_id)
        _settings = [i for k, v in native_stringify_dict(settings, keys_only=False).items() for i in ['-s', f"{k}={v}"]]
        _args = [i for k, v in native_stringify_dict(args, keys_only=False).items() for i in ['-a', f"{k}={v}"]]
        env = {
            'SCRAPY_PROJECT': project.id(),
            'SCRAPYD_SPIDER': spider,
            'SCRAPYD_JOB': job_id,
        }
        labels = {
            self.LABEL_JOB_ID: job_id,
            self.LABEL_PROJECT: project.id(),
            self.LABEL_SPIDER: spider,
        }
        env_from = []
        env_config = project.env_config()
        if env_config:
            env_from.append(kubernetes.client.V1EnvFromSource(
                config_map_ref=kubernetes.client.V1ConfigMapEnvSource(name=env_config, optional=False)
            ))
        env_secret = project.env_secret()
        if env_secret:
            env_from.append(kubernetes.client.V1EnvFromSource(
                secret_ref=kubernetes.client.V1SecretEnvSource(name=env_secret, optional=False)
            ))
        resources = project.resources(spider)
        container = kubernetes.client.V1Container(
            name=job_name,
            image=project.repository() + ':' + version,
            args=['scrapy', 'crawl', spider, *_args, *_settings],
            env=[kubernetes.client.V1EnvVar(k, v) for k, v in env.items()],
            env_from=env_from,
            resources=kubernetes.client.V1ResourceRequirements(
                requests=resources.get('requests', {}),
                limits=resources.get('limits', {})
            )
        )
        pod_template = kubernetes.client.V1PodTemplateSpec(
            metadata=kubernetes.client.V1ObjectMeta(name=job_name, labels=labels),
            spec=kubernetes.client.V1PodSpec(
                containers=[container],
                share_process_namespace=True, # an init process for cancel
                restart_policy='Never',
                image_pull_secrets=[kubernetes.client.V1LocalObjectReference(s) for s in [self._pull_secret] if s]
            )
        )
        job_spec = kubernetes.client.V1JobSpec(
            template=pod_template,
            suspend=start_suspended,
            completions=1,
            backoff_limit=0 # don't retry (TODO reconsider)
        )
        job = kubernetes.client.V1Job(
            api_version='batch/v1',
            kind='Job',
            metadata=kubernetes.client.V1ObjectMeta(name=job_name, labels=labels),
            spec=job_spec
        )
        r = self._k8s_batch.create_namespaced_job(namespace=self._namespace, body=job)

    def cancel(self, project, job_id, signal):
        job = self._get_job(project, job_id)
        if not job:
            return None

        prevstate = self._k8s_job_to_scrapyd_status(job)
        if prevstate == 'finished':
            pass # nothing to do
        elif prevstate == 'running':
            # kill pod (retry is disabled, so there should be only one pod)
            pod = self._get_pod(project, job_id)
            if pod: # if a pod has just ended, we're good already, don't kill
                self._k8s_kill(pod.metadata.name, Signals['SIG' + signal].value)
        else:
            # not started yet, delete job
            self._k8s_batch.delete_namespaced_job(
                namespace=self._namespace,
                name=job.metadata.name,
                body=kubernetes.client.V1DeleteOptions(
                    propagation_policy='Foreground',
                    grace_period_seconds=0
                )
            )
        return prevstate

    def enable_joblogs(self, config):
        joblogs_config = config.joblogs()
        if joblogs_config and joblogs_config.get('storage_provider') is not None:
            log_handler = KubernetesJobLogHandler(config)
            self.resource_watcher.subscribe(log_handler.handle_events)
            logger.info("Job logs handler started.")
        else:
            logger.warning("No storage provider configured; job logs will not be uploaded.")

    def unsuspend_job(self, job_id: str):
        job_name = self._get_job_name(job_id)
        if not job_name:
            logger.error(f"Cannot unsuspend job {job_id}: job name not found.")
            return False
        try:
            self._k8s_batch.patch_namespaced_job(
                name=job_name,
                namespace=self._namespace,
                body={'spec': {'suspend': False}}
            )
            logger.info(f"Job {job_id} unsuspended.")
            return True
        except Exception as e:
            logger.exception(f"Error unsuspending job {job_id}: {e}")
            return False

    def get_running_jobs_count(self) -> int:
        """
        Returns the number of currently active (unsuspended, not completed, not failed) jobs.
        """
        label_selector = f"{self.LABEL_JOB_ID}"
        jobs = self._k8s_batch.list_namespaced_job(
            namespace=self._namespace,
            label_selector=label_selector
        )

        active_jobs = []
        for job in jobs.items:
            job_name = job.metadata.name
            is_suspended = job.spec.suspend
            is_completed = job.status.completion_time is not None
            has_failed = job.status.failed is not None and job.status.failed > 0
            logger.debug(f"Job {job_name}: suspended={is_suspended}, completed={is_completed}, failed={has_failed}")

            if not is_suspended and not is_completed and not has_failed:
                active_jobs.append(job)

        logger.debug(f"Active jobs: {[job.metadata.name for job in active_jobs]}")
        logger.debug(f"Found {len(active_jobs)} active jobs.")

        return len(active_jobs)

    def list_suspended_jobs(self, label_selector: str = ""):
        try:
            jobs = self._k8s_batch.list_namespaced_job(
                namespace=self._namespace,
                label_selector=label_selector
            )
            # Filter jobs where spec.suspend == True
            suspended_jobs = [job for job in jobs.items if job.spec.suspend]
            logger.debug(f"Found {len(suspended_jobs)} suspended jobs.")
            return suspended_jobs
        except Exception as e:
            logger.exception(f"Error listing suspended jobs: {e}")
            return []

    def _parse_job(self, job):
        state = self._k8s_job_to_scrapyd_status(job)
        return {
            'id': job.metadata.labels.get(self.LABEL_JOB_ID),
            'state': state,
            'project': job.metadata.labels.get(self.LABEL_PROJECT),
            'spider': job.metadata.labels.get(self.LABEL_SPIDER),
            'start_time': format_datetime_object(job.status.start_time) if state in ['running', 'finished'] else None,
            'end_time': format_datetime_object(job.status.completion_time) if job.status.completion_time and state == 'finished' else None,
        }

    def _get_job(self, project, job_id):
        label = self.LABEL_JOB_ID + '=' + job_id
        r = self._k8s_batch.list_namespaced_job(namespace=self._namespace, label_selector=label)
        if not r or not r.items:
            return None
        job = r.items[0]

        if job.metadata.labels.get(self.LABEL_PROJECT) != project:
            # TODO log error
            return None

        return job

    def _get_job_name(self, job_id: str):
        label_selector = f"{self.LABEL_JOB_ID}={job_id}"
        jobs = self._k8s_batch.list_namespaced_job(namespace=self._namespace, label_selector=label_selector)
        if not jobs.items:
            logger.error(f"No job found with job_id={job_id}")
            return None
        return jobs.items[0].metadata.name

    def _get_pod(self, project, job_id):
        label = self.LABEL_JOB_ID + '=' + job_id
        r = self._k8s.list_namespaced_pod(namespace=self._namespace, label_selector=label)
        if not r or not r.items:
            return None
        pod = r.items[0]

        if pod.metadata.labels.get(self.LABEL_PROJECT) != project:
            # TODO log error
            return None

        return pod

    def _k8s_job_to_scrapyd_status(self, job):
        if job.status.ready:
            return 'running'
        elif job.status.succeeded:
            return 'finished'
        elif job.status.failed:
            return 'finished'
        else:
            return 'pending'

    def _k8s_job_name(self, project, job_id):
        return '-'.join(('scrapyd', project, job_id))

    def _k8s_kill(self, pod_name, signal):
        # exec needs stream, which modifies client, so use separate instance
        k8s = kubernetes.client.CoreV1Api()
        resp = kubernetes.stream.stream(
            k8s.connect_get_namespaced_pod_exec,
            pod_name,
            namespace=self._namespace,
            # this is a bit blunt, bit it works and is usually available
            command=['/usr/sbin/killall5', '-' + str(signal)],
            stderr=True
        )
        # TODO figure out how to get return value