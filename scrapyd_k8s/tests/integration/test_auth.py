#!/usr/bin/env python3
import os
import requests

BASE_URL = os.getenv('TEST_BASE_URL', 'http://localhost:6800')

def test_root_no_auth():
    response = requests.get(BASE_URL)
    assert response.status_code == 401
    assert 'scrapyd-k8s' not in response.text

def test_root_incorrect_auth():
    session = requests.Session()
    session.auth = ('nonexistant', 'incorrect')
    response = session.get(BASE_URL)
    assert response.status_code == 403
    assert 'scrapyd-k8s' not in response.text

def test_root_correct_auth():
    session = requests.Session()
    session.auth = ('foo', 'secret') # needs to match test_auth.conf
    response = session.get(BASE_URL)
    assert response.status_code == 200
    assert response.headers['Content-Type'] == 'text/html; charset=utf-8'
    assert 'scrapyd-k8s' in response.text
    assert '</html>' in response.text

# TODO this is going wrong now (!)
#def test_healthz_ok():
#    response = requests.get(BASE_URL + '/healthz')
#    assert response.status_code == 200

def test_daemonstatus_no_auth():
    response = requests.get(BASE_URL + '/daemonstatus.json')
    assert response.status_code == 401

def test_daemonstatus_incorrect_auth():
    session = requests.Session()
    session.auth = ('nonexistant', 'incorrect')
    response = requests.get(BASE_URL + '/daemonstatus.json')
    assert response.status_code == 403
    assert 'ok' not in response.text

def test_daemonstatus_correct_auth():
    session = requests.Session()
    session.auth = ('foo', 'secret') # needs to match test_auth.conf
    response = requests.get(BASE_URL + '/daemonstatus.json')
    assert response.status_code == 200
    assert response.headers['Content-Type'] == 'application/json'
    assert response.json()['status'] == 'ok'
