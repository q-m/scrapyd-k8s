import os
import requests
import time

BASE_URL = os.getenv('TEST_BASE_URL', 'http://localhost:6800')
RUN_PROJECT = os.getenv('TEST_RUN_PROJECT', 'example')
RUN_VERSION = os.getenv('TEST_RUN_VERSION', 'latest')
RUN_SPIDER = os.getenv('TEST_RUN_SPIDER', 'static')
MAX_WAIT = int(os.getenv('TEST_MAX_WAIT', '6'))

def test_max_proc_zero():
    """With max_proc=0, any scheduled job remains in the 'pending' state"""
    # Schedule a job
    response = requests.post(BASE_URL + '/schedule.json', data={
        'project': RUN_PROJECT, 'spider': RUN_SPIDER, '_version': RUN_VERSION
    })
    assert_response_ok(response)
    jobid = response.json()['jobid']
    assert jobid is not None

    # Wait and make sure the job remains in the pending state
    assert_listjobs(pending=jobid)
    time.sleep(MAX_WAIT)
    assert_listjobs(pending=jobid)

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
