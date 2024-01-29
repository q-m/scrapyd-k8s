import json
import subprocess

class Local:

    def __init__(self, config):
        pass

    def listtags(self, repo):
        """Returns available tags from local docker images"""
        r = subprocess.check_output(['docker', 'image', 'ls', repo, '--format', '{{ .Tag }}']).decode('utf-8')
        tags = r.split('\n')
        # TODO error handling
        return [t for t in tags if t and t != '<none>']

    def listspiders(self, repo, project, version):
        """Returns available spiders from a local docker image"""
        r = subprocess.check_output(['docker', 'image', 'inspect', repo + ':' + version, '--format', '{{ index .Config.Labels "org.scrapy.spiders" }}']).decode('utf-8')
        spiders = r.split(',')
        spiders = [s.strip() for s in spiders]
        return [s for s in spiders if s]

