import docker

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

    def listjobs(self, project=None):
        label = self.LABEL_PROJECT + ('=%s'%(project) if project else '')
        jobs = self._docker.containers.list(all=True, filters={ 'label': label })
        jobs = [self._parse_job(j) for j in jobs]
        return jobs

    def schedule(self, repository, project, version, spider, job_id, env_config, env_secret, settings, args):
        _settings = [i for s in settings for i in ['-s', s]]
        _args = [i for a in args for i in ['-a', a]]
        env = {
            'SCRAPY_PROJECT': project,
            'SCRAPYD_SPIDER': spider,
            'SCRAPYD_JOB': job_id,
        } # TODO env_source handling
        c = self._docker.containers.create(
            image=repository + ':' + version,
            command=['scrapy', 'crawl', spider, *_args, *_settings],
            environment=env,
            labels={
                self.LABEL_JOB_ID: job_id,
                self.LABEL_PROJECT: project,
                self.LABEL_SPIDER: spider,
            },
            name='_'.join(['scrapyd', project, job_id]),
            detach=True
        )

    def cancel(self, project, job_id, signal):
        c = self._get_container(project, job_id)
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
   
    def _get_container(self, project, job_id):
        filters = { 'label': self.LABEL_JOB_ID + '=' + job_id }
        c = self._docker.containers.list(all=True, filters=filters)
        if not c:
            return None
        c = c[0]

        if c.labels.get(self.LABEL_PROJECT) != project:
            return None

        return c

    def _docker_to_scrapyd_status(self, status):
        return self.STATUS_MAP.get(status, status)
