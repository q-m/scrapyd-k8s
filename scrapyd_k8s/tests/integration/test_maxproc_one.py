import os
import requests
import time

BASE_URL = os.getenv('TEST_BASE_URL', 'http://localhost:6800')
RUN_PROJECT = os.getenv('TEST_RUN_PROJECT', 'example')
RUN_VERSION = os.getenv('TEST_RUN_VERSION', 'latest')
RUN_SPIDER = os.getenv('TEST_RUN_SPIDER', 'static')
MAX_WAIT = int(os.getenv('TEST_MAX_WAIT', '6'))
STATIC_SLEEP = float(os.getenv('TEST_STATIC_SLEEP', '2'))

def test_max_proc_one():
    """With max_proc=1, two jobs are scheduled, and are run after each other. """
    # Schedule a job
    response = requests.post(BASE_URL + '/schedule.json', data={
        'project': RUN_PROJECT, 'spider': RUN_SPIDER, '_version': RUN_VERSION,
        'setting': 'STATIC_SLEEP=%d' % STATIC_SLEEP
    })
    assert_response_ok(response)
    jobid1 = response.json()['jobid']
    assert jobid1 is not None
    # Schedule another job right away, which remains queued
    response = requests.post(BASE_URL + '/schedule.json', data={
        'project': RUN_PROJECT, 'spider': RUN_SPIDER, '_version': RUN_VERSION,
        'setting': 'STATIC_SLEEP=%d' % STATIC_SLEEP
    })
    assert_response_ok(response)
    jobid2 = response.json()['jobid']
    assert jobid2 is not None

    # Wait and make sure the job remains in the pending state
    listjobs_wait(jobid1, 'running')
    assert_listjobs(pending=jobid2, running=jobid1)
    # Wait until the first is finished and the second starts
    listjobs_wait(jobid1, 'finished', max_wait=STATIC_SLEEP+MAX_WAIT)
    listjobs_wait(jobid2, 'running')
    # Wait until the second is finished too
    listjobs_wait(jobid2, 'finished', max_wait=STATIC_SLEEP+MAX_WAIT)

def assert_response_ok(response):
    assert response.status_code == 200
    assert response.headers['Content-Type'] == 'application/json'
    assert response.json()['status'] == 'ok'

def assert_listjobs(pending=None, running=None, finished=None):
    response = requests.get(BASE_URL + '/listjobs.json')
    assert_response_ok(response)
    if pending:
        assert len(response.json()['pending']) == 1
        assert response.json()['pending'][0]['id'] == pending
        return response.json()['pending'][0]
    else:
        assert response.json()['pending'] == []
    if running:
        assert len(response.json()['running']) == 1
        assert response.json()['running'][0]['id'] == running
        return response.json()['running'][0]
    else:
        assert response.json()['running'] == []
    # finished may contain other jobs
    if finished:
        matches = [j for j in response.json()['finished'] if j['id'] == finished]
        assert len(matches) == 1
        return matches[0]

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
