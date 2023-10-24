import re
from configparser import ConfigParser
from importlib import import_module

class Config:
    def __init__(self, file='scrapyd_k8s.conf'):
        self._config = ConfigParser()
        self._config.read(file)
        self._projects = [s[8:] for s in self._config.sections() if re.match(r'project\.', s)]

    def scrapyd(self):
        return self._config['scrapyd']
    
    def repository_cls(self):
        repo = self._config['scrapyd'].get('repository', 'scrapyd_k8s.repository.Remote')
        pkg, cls = repo.rsplit('.', 1)
        return getattr(import_module(pkg), cls)
    
    def launcher_cls(self):
        repo = self._config['scrapyd'].get('launcher', 'scrapyd_k8s.launcher.K8s')
        pkg, cls = repo.rsplit('.', 1)
        return getattr(import_module(pkg), cls)

    def listprojects(self):
        return self._projects

    def project(self, project):
        if project in self._projects:
            return self._config['project.' + project]

