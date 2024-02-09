import json
import subprocess

class Remote:

    def __init__(self, config):
        pass

    def listtags(self, repo):
        """Returns available tags from a docker repository"""
        r = json.loads(subprocess.check_output(['skopeo', 'list-tags', 'docker://' + repo]))
        # TODO error handling
        return r['Tags']

    def listspiders(self, repo, project, version):
        """Returns available spiders from a docker image, or None on error."""
        r = subprocess.run(['skopeo', 'inspect', 'docker://' + repo + ':' + version], capture_output=True, text=True)
        if r.returncode != 0: return None
        j = json.loads(r.stdout)
        labels = (j['Labels'] or {})
        # TODO more useful error when labels are absent
        # TODO warn if org.scrapy.project is different from supplied project
        if 'org.scrapy.spiders' not in labels:
            return None
        if labels['org.scrapy.spiders'].strip() == '':
            return []
        spiders = labels['org.scrapy.spiders'].split(',')
        return [s.strip() for s in spiders]