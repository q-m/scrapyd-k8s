#!/usr/bin/env python3
import gzip
import os
import pytest
import requests
import shutil
import time

BASE_URL = os.getenv('TEST_BASE_URL', 'http://localhost:6800')
RUN_PROJECT = os.getenv('TEST_RUN_PROJECT', 'example')
RUN_VERSION = os.getenv('TEST_RUN_VERSION', 'latest')
RUN_SPIDER = os.getenv('TEST_RUN_SPIDER', 'static')
MAX_WAIT = int(os.getenv('TEST_MAX_WAIT', '6'))
STATIC_SLEEP = float(os.getenv('TEST_STATIC_SLEEP', '2'))
WITH_K8S = bool(os.getenv('TEST_WITH_K8S'))
LOG_BASE = os.getenv('TEST_LOG_BASE', '/tmp/joblogs')

LOG_DIR_LIVE = os.path.join(LOG_BASE, 'live')
LOG_DIR_CONT = os.path.join(LOG_BASE, 'container', 'a')

@pytest.mark.skipif(not WITH_K8S, reason="joblogs only implemented for Kubernetes")
def test_container():
  # Schedule a job
  response = requests.post(BASE_URL + '/schedule.json', data={
      'project': RUN_PROJECT, 'spider': RUN_SPIDER, '_version': RUN_VERSION,
      'setting': 'STATIC_SLEEP=%d' % STATIC_SLEEP
  })
  assert_response_ok(response)
  jobid = response.json()['jobid']
  assert jobid is not None

  # Wait until finished, and a bit more to finish log processing
  listjobs_wait(jobid, 'finished', max_wait=STATIC_SLEEP+MAX_WAIT)
  time.sleep(1)

  # Make sure we find logfile in container storage (configured as local storage)
  log_path_cont = os.path.join(LOG_DIR_CONT, 'logs', RUN_PROJECT, RUN_SPIDER, jobid + '.log.gz')
  assert(os.path.isfile(log_path_cont))
  with gzip.open(log_path_cont, 'rb') as f:
    log = f.read().decode('utf-8')
    # bot name in first lines
    assert('(bot: %s)' % RUN_PROJECT in log)
    # 'Spider finished' in last lines
    assert('Spider closed (finished)' in log)

def assert_response_ok(response):
    assert response.status_code == 200
    assert response.headers['Content-Type'] == 'application/json'
    assert response.json()['status'] == 'ok'

def listjobs_wait(jobid, state, max_wait=MAX_WAIT):
    started = time.monotonic()
    while time.monotonic() - started < max_wait:
        response = requests.get(BASE_URL + '/listjobs.json')
        assert_response_ok(response)
        for j in response.json()[state]:
            if j['id'] == jobid:
                return True
        time.sleep(0.5)
    assert False, 'Timeout waiting for job state change'
