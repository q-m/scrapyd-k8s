import docker

class Local:

    def __init__(self, config):
        self._docker = docker.from_env()

    def listtags(self, repo):
        """Returns available tags from local docker images"""
        images = self._docker.images.list(repo)
        tags = [i.tags[0].split(':')[-1] for i in images if i.tags]
        # TODO error handling
        return tags

    def listspiders(self, repo, project, version):
        """Returns available spiders from a local docker image, or None on error."""
        try:
            image = self._docker.images.get(repo + ':' + version)
            r = image.labels.get('org.scrapy.spiders')
            if not r: return None
            spiders = r.split(',')
            spiders = [s.strip() for s in spiders]
            return [s for s in spiders if s]
        except docker.errors.ImageNotFound:
            return None

