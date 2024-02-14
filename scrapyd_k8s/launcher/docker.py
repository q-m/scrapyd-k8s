import re
import docker
from ..utils import native_stringify_dict

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
        c = self._docker.containers.run(
            image=project.repository() + ':' + version,
            command=['scrapy', 'crawl', spider, *_args, *_settings],
            environment=env,
            labels={
                self.LABEL_JOB_ID: job_id,
            },
            name='_'.join(['scrapyd', project.id(), job_id]),
            detach=True,
            mem_limit=resources.get('limits', {}).get('memory'),
            cpu_quota=_str_to_micro(resources.get('limits', {}).get('cpu'))
        )

    def cancel(self, project_id, job_id, signal):
        c = self._get_container(project_id, job_id)
        if not c:
            return None

        prevstate = self._docker_to_scrapyd_status(c.status)
        if c.status == 'created' or c.status == 'scheduled':
            c.remove()
        elif c.status == 'running':
            c.kill(signal='SIG' + signal)
        return prevstate

    def _parse_job(self, c):
        return {
            'id': c.labels.get(self.LABEL_JOB_ID),
            'state': self._docker_to_scrapyd_status(c.status),
            'project': c.labels.get(self.LABEL_PROJECT),
            'spider': c.labels.get(self.LABEL_SPIDER)
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
