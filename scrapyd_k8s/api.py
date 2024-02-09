#!/usr/bin/env python3
import uuid

from flask import Flask, request
from markupsafe import escape
from natsort import natsort_keygen, ns

from .config import Config

app = Flask(__name__)
config = Config()
repository = (config.repository_cls())(config)
launcher = (config.launcher_cls())(config)

@app.get("/")
def home():
    return "<html><body><h1>scrapyd-k8s</h1></body></html>"

@app.get("/daemonstatus.json")
def api_daemonstatus():
    return { "status": "ok", "spiders": 0 }

@app.post("/schedule.json")
def api_schedule():
    project_id = request.form['project']
    project = config.project(project_id)
    if not project: return error('project not found')
    spider = request.form['spider']
    settings = dict(x.split('=', 1) for x in request.form.getlist('setting'))
    job_id = request.form.get('jobid', uuid.uuid1().hex)
    # priority = request.form.get('priority') or 0 # TODO implement priority
    _version = request.form.get('_version', 'latest') # TODO allow customizing latest tag
    # any other parameter is passed as spider argument
    args = { k: v for k, v in request.form.items() if k not in ('project', 'spider', 'setting', 'jobid', 'priority', '_version') }
    env_config, env_secret = project.get('env_config'), project.get('env_secret')
    jobid = launcher.schedule(project['repository'], project_id, _version, spider, job_id, env_config, env_secret, settings, args)
    return { 'status': 'ok', 'jobid': job_id }

@app.post("/cancel.json")
def api_cancel():
    project_id = request.form['project']
    job_id = request.form['job']
    signal = request.form.get('signal', 'TERM')
    # TODO get job state and return in prevstate
    prevstate = launcher.cancel(project_id, job_id, signal)
    if not prevstate: return error('job not found')
    return { 'status': 'ok', 'prevstate': prevstate }

@app.get("/listprojects.json")
def api_listprojects():
    return { 'status': 'ok', 'projects': config.listprojects() }

@app.get("/listversions.json")
def api_listversions():
    project_id = request.args['project']
    project = config.project(project_id)
    if not project: return error('project not found')
    tags = repository.listtags(project['repository'])
    tags = [t for t in tags if not t.startswith('sha-')]
    tags.sort(key=natsort_keygen(alg=ns.NUMAFTER))
    return { 'status': 'ok', 'versions': tags }

@app.get("/listspiders.json")
def api_listspiders():
    project_id = request.args['project']
    project = config.project(project_id)
    if not project: return error('project not found')
    _version = request.args.get('_version', 'latest') # TODO allow customizing latest tag
    spiders = repository.listspiders(project['repository'], project_id, _version)
    return { 'status': 'ok', 'spiders': spiders }

@app.get("/listjobs.json")
def api_listjobs():
    project_id = request.args.get('project')
    jobs = launcher.listjobs(project_id)
    pending = [j for j in jobs if j['state'] == 'pending']
    running = [j for j in jobs if j['state'] == 'running']
    finished = [j for j in jobs if j['state'] == 'finished']
    # TODO perhaps remove state from jobs
    return { 'status': 'ok', 'pending': pending, 'running': running, 'finished': finished }

def error(msg):
    return { 'status': 'error', 'message': msg }

def run():
    host = config.scrapyd().get('bind_address', '127.0.0.1')
    port = config.scrapyd().get('http_port', '6800')
    app.run(host=host, port=port)