import re
from configparser import ConfigParser
from importlib import import_module

from .logging import setup_logging

class Config:
    def __init__(self):
        self._config = ConfigParser(empty_lines_in_values=False)
        self._projects = []
        self._launcher = None
        self._repository = None

    def read(self, files=['scrapyd_k8s.conf']):
        self._config.read(files)
        self._update()

    def _update(self):
        self._projects = [s[8:] for s in self._config.sections() if re.match(r'^project\.[^\.]+$', s)]
        setup_logging(self.scrapyd().get('log_level', 'INFO'))

    def scrapyd(self):
        return self._config['scrapyd']

    def repository(self):
        if not self._repository:
            self._repository = (self._repository_cls())(self)
        return self._repository

    def _repository_cls(self):
        repo = self._config['scrapyd'].get('repository', 'scrapyd_k8s.repository.Remote')
        pkg, cls = repo.rsplit('.', 1)
        return getattr(import_module(pkg), cls)

    def launcher(self):
        if not self._launcher:
            self._launcher = (self._launcher_cls())(self)
        return self._launcher

    def _launcher_cls(self):
        repo = self._config['scrapyd'].get('launcher', 'scrapyd_k8s.launcher.K8s')
        pkg, cls = repo.rsplit('.', 1)
        return getattr(import_module(pkg), cls)

    def joblogs(self):
        if self._config.has_section('joblogs'):
            return self._config['joblogs']
        else:
            return None

    def joblogs_storage(self, provider):
        if not self._config.has_section('joblogs.storage.%s' % provider):
            return None
        return self._config['joblogs.storage.%s' % provider]

    def listprojects(self):
        return self._projects

    def project(self, project):
        if project in self._projects:
            return ProjectConfig(self._config, project, self._config['project.' + project])

    def namespace(self):
        return self.scrapyd().get('namespace', 'default')

class ProjectConfig:
    def __init__(self, config, projectid, projectconfig):
        self._id = projectid
        self._config = config
        self._project = projectconfig

    def id(self):
        return self._id

    def repository(self):
        return self._project['repository']

    def env_config(self):
        return self._project.get('env_config')

    def env_secret(self):
        return self._project.get('env_secret')

    def resources(self, spider=None):
        r = { 'requests': {}, 'limits': {} }
        self._get_resources('default.resources', r)
        self._get_resources('.'.join(['project', self._id, 'resources']), r)
        if spider:
            self._get_resources('.'.join(['project', self._id, spider, 'resources']), r)
        return r

    def _get_resources(self, section, dest):
        if self._config.has_section(section):
            for k, v in self._config[section].items():
                if k.startswith('requests_'):
                    dest['requests'][k[9:]] = v
                if k.startswith('limits_'):
                    dest['limits'][k[7:]] = v
        return dest
