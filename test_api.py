#!/usr/bin/env python3
import os
import pytest
import requests
import time


BASE_URL = os.getenv('TEST_BASE_URL', 'http://localhost:6800')
AVAIL_PROJECTS = os.getenv('TEST_AVAILABLE_PROJECTS', 'example').split(',')
AVAIL_VERSIONS = os.getenv('TEST_AVAILABLE_VERSIONS', 'latest').split(',')
AVAIL_SPIDERS = os.getenv('TEST_AVAILABLE_SPIDERS', 'quotes,static').split(',')
RUN_PROJECT = os.getenv('TEST_RUN_PROJECT', 'example')
RUN_VERSION = os.getenv('TEST_RUN_VERSION', 'latest')
RUN_SPIDER = os.getenv('TEST_RUN_SPIDER', 'static')
MAX_WAIT = int(os.getenv('TEST_MAX_WAIT', '6'))
STATIC_SLEEP = float(os.getenv('TEST_STATIC_SLEEP', '2'))

def test_root_ok():
    response = requests.get(BASE_URL)
    assert response.status_code == 200
    assert response.headers['Content-Type'] == 'text/html; charset=utf-8'
    assert 'scrapyd-k8s' in response.text
    assert '</html>' in response.text

def test_healthz_ok():
    response = requests.get(BASE_URL + '/healthz')
    assert response.status_code == 200

def test_daemonstatus_ok():
    response = requests.get(BASE_URL + '/daemonstatus.json')
    assert_response_ok(response)
    # TODO assert response.json() == { 'status': 'ok', ... }


def test_listprojects_ok():
    response = requests.get(BASE_URL + '/listprojects.json')
    assert_response_ok(response)

    json = response.json()
    assert json['projects'] == AVAIL_PROJECTS
    assert 'node_name' in json


def test_listversions_ok():
    response = requests.get(BASE_URL + '/listversions.json?project=' + RUN_PROJECT)
    assert_response_ok(response)

    json = response.json()
    assert json['versions'] == AVAIL_VERSIONS
    assert 'node_name' in json

def test_listversions_project_missing():
    response = requests.get(BASE_URL + '/listversions.json')
    assert_response_error(response, 400)

def test_listversions_project_not_found():
    response = requests.get(BASE_URL + '/listversions.json?project=' + 'nonexistant')
    assert_response_error(response, 404)


def test_listspiders_ok():
    response = requests.get(BASE_URL + '/listspiders.json?project=' + RUN_PROJECT + '&_version=' + RUN_VERSION)
    assert_response_ok(response)

    json = response.json()
    assert json['spiders'] == AVAIL_SPIDERS
    assert 'node_name' in json


def test_listspiders_ok_without_version():
    response = requests.get(BASE_URL + '/listspiders.json?project=' + RUN_PROJECT)
    assert_response_ok(response)

    json = response.json()
    assert json['spiders'] == AVAIL_SPIDERS
    assert 'node_name' in json

def test_listspiders_project_missing():
    response = requests.get(BASE_URL + '/listspiders.json')
    assert_response_error(response, 400)

def test_listspiders_project_not_found():
    response = requests.get(BASE_URL + '/listspiders.json?project=' + 'nonexistant' + '&_version=' + RUN_VERSION)
    assert_response_error(response, 404)

def test_listspiders_version_not_found():
    response = requests.get(BASE_URL + '/listspiders.json?project=' + RUN_PROJECT + '&_version=' + 'nonexistant')
    assert_response_error(response, 404)

def test_schedule_project_missing():
    response = requests.post(BASE_URL + '/schedule.json', data={})
    assert_response_error(response, 400)

def test_schedule_project_not_found():
    response = requests.post(BASE_URL + '/schedule.json', data={ 'project': 'nonexistant' })
    assert_response_error(response, 400)

def test_schedule_spider_missing():
    response = requests.post(BASE_URL + '/schedule.json', data={ 'project': RUN_PROJECT })
    assert_response_error(response, 400)

# scheduling a non-existing spider will try to start it, so no error
# scheduling a non-existing project version will try to start it, so no error

def test_cancel_project_missing():
    response = requests.post(BASE_URL + '/cancel.json', data={})
    assert_response_error(response, 400)

# we don't test cancelling a spider from a project not in the config file
def test_cancel_jobid_missing():
    response = requests.post(BASE_URL + '/cancel.json', data={ 'project': RUN_PROJECT })
    assert_response_error(response, 400)

# TODO test cancel with invalid signal (currently returns server error, could be improved)
def test_scenario_regular_ok():
    scenario_regular({
        'project': RUN_PROJECT, '_version': RUN_VERSION, 'spider': RUN_SPIDER,
        'setting': 'STATIC_SLEEP=%d' % STATIC_SLEEP
    })

def test_scenario_regular_ok_without_version():
    scenario_regular({
        'project': RUN_PROJECT, 'spider': RUN_SPIDER,
        'setting': 'STATIC_SLEEP=%d' % STATIC_SLEEP
    })

# TODO test_scenario_cancel_scheduled_ok (needs a way to make sure a job is not running yet)
def test_scenario_cancel_running_finished_ok():
    assert_listjobs()
    # schedule a new job and wait until it is running
    response = requests.post(BASE_URL + '/schedule.json', data={
        'project': RUN_PROJECT, '_version': RUN_VERSION, 'spider': RUN_SPIDER,
        'setting': 'STATIC_SLEEP=%d' % (STATIC_SLEEP * 5)
    })
    assert_response_ok(response)
    jobid = response.json()['jobid']
    assert jobid is not None
    # wait until the job is running
    listjobs_wait(jobid, 'running')
    # cancel the job, with the kill signal to make it stop right away
    response = requests.post(BASE_URL + '/cancel.json', data={
        'project': RUN_PROJECT, 'job': jobid, 'signal': 'KILL'
    })
    assert_response_ok(response)

    json = response.json()
    assert json['prevstate'] == 'running'
    assert 'node_name' in json

    # wait until the job has stopped
    listjobs_wait(jobid, 'finished')
    jobinfo = assert_listjobs(finished=jobid)
    assert jobinfo == { 'id': jobid, 'project': RUN_PROJECT, 'spider': RUN_SPIDER, 'state': 'finished' }
    # then cancel it again, though nothing would happen
    response = requests.post(BASE_URL + '/cancel.json', data={ 'project': RUN_PROJECT, 'job': jobid })
    assert_response_ok(response)

    json = response.json()
    assert json['prevstate'] == 'finished'
    assert 'node_name' in json

def scenario_regular(schedule_args):
    assert_listjobs()
    # schedule a job
    response = requests.post(BASE_URL + '/schedule.json', data=schedule_args)
    assert_response_ok(response)
    jobid = response.json()['jobid']
    assert jobid is not None
    # wait until the job is running
    listjobs_wait(jobid, 'running')
    jobinfo = assert_listjobs(running=jobid)
    assert jobinfo == { 'id': jobid, 'project': RUN_PROJECT, 'spider': RUN_SPIDER, 'state': 'running' }
    # wait until the job has finished
    listjobs_wait(jobid, 'finished')
    # check listjobs output
    jobinfo = assert_listjobs(finished=jobid)
    assert jobinfo == { 'id': jobid, 'project': RUN_PROJECT, 'spider': RUN_SPIDER, 'state': 'finished' }

def assert_response_ok(response):
    assert response.status_code == 200
    assert response.headers['Content-Type'] == 'application/json'
    assert response.json()['status'] == 'ok'

def assert_response_error(response, status):
    assert response.status_code == status
    assert response.headers['Content-Type'] == 'application/json'
    assert response.json()['status'] == 'error'
    assert response.json()['message'] is not None

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

def listjobs_wait(jobid, state):
    started = time.monotonic()
    while time.monotonic() - started < MAX_WAIT:
        response = requests.get(BASE_URL + '/listjobs.json')
        assert_response_ok(response)
        for j in response.json()[state]:
            if j['id'] == jobid:
                return True
        time.sleep(0.5)
    assert False, 'Timeout waiting for job state change'
