import os
import pytest
import subprocess
import time
import requests
import uuid
import shutil

USE_REAL_MINIKUBE = os.environ.get("USE_REAL_MINIKUBE", "false").lower() == "true"


def is_minikube_running():
    try:
        proc = subprocess.run(
            ["minikube", "status", "--output=json"],
            capture_output=True, text=True, check=True, timeout=10
        )
        return "Running" in proc.stdout
    except Exception:
        return False


@pytest.fixture(scope="session")
def ensure_minikube():
    """If USE_REAL_MINIKUBE is true, ensure minikube is up and context set."""
    if not USE_REAL_MINIKUBE:
        pytest.skip("Skipping real k8s tests unless USE_REAL_MINIKUBE=true is set.")

    if not shutil.which("minikube"):
        pytest.skip("Minikube not installed, skipping.")

    if not is_minikube_running():
        try:
            proc = subprocess.run(
                ["minikube", "start", "--driver=docker"],
                check=True, capture_output=True, text=True, timeout=180
            )
            print(proc.stdout)
        except subprocess.CalledProcessError as e:
            pytest.skip(f"Failed to start minikube: {e.stderr}")

    # Force context to minikube
    try:
        subprocess.run(["kubectl", "config", "use-context", "minikube"], check=True)
    except subprocess.CalledProcessError:
        pytest.skip("Failed to use minikube context.")

    # Check cluster
    try:
        subprocess.run(["kubectl", "cluster-info"], check=True)
    except subprocess.CalledProcessError:
        pytest.skip("kubectl cluster-info failed.")

    yield

    # Clean up all Kubernetes resources after all tests
    print("Final cleanup of all resources...")
    subprocess.run(["kubectl", "delete", "all", "--all"], check=False)
    # Don't delete minikube itself - leave that to the user


@pytest.fixture(scope="session")
def minikube_env():
    result = subprocess.run(["minikube", "docker-env"], check=True, capture_output=True, text=True)

    env = os.environ.copy()
    for line in result.stdout.split('\n'):
        if line.startswith("export "):
            key, value = line[len("export "):].split("=", 1)
            env[key] = value.strip('"')

    yield env


@pytest.fixture(scope="session", autouse=True)
def ensure_scrapyd_image(minikube_env):
    print("Building test container...")
    subprocess.run(["docker", "build", "-t", "scrapyd-k8s-test:latest", "."], check=True, env=minikube_env)

    yield

    print("Removing test container...")
    subprocess.run(["docker", "rmi", "scrapyd-k8s-test:latest"], check=False, env=minikube_env)


def wait_for_scrapyd_ready(label_selector="app.kubernetes.io/name=scrapyd-k8s", timeout=40):
    """
    Wait until a pod matching label_selector is Running, then sleep 5s.
    """
    import time
    start = time.time()
    ready = False

    print(f"Waiting for pod with label {label_selector} to be ready (timeout: {timeout}s)...")

    while time.time() - start < timeout:
        get_pods = subprocess.run(
            ["kubectl", "get", "pods", "--selector", label_selector],
            capture_output=True, text=True
        )
        print(f"Current pods: {get_pods.stdout}")

        if "Running" in get_pods.stdout:
            print(f"Pod is now Running. Waiting a moment for internal initialization...")
            # give it a few seconds for internal init
            time.sleep(3)
            ready = True
            break

    if not ready:
        # Get deployment events for debugging
        print("Pod not ready in time. Checking events:")
        events = subprocess.run(
            ["kubectl", "get", "events", "--sort-by=.metadata.creationTimestamp"],
            capture_output=True, text=True
        )
        print(events.stdout)
        pytest.fail(f"No 'Running' pods found with label {label_selector} after {timeout}s")

    return True


@pytest.fixture
def scrapyd_service(ensure_minikube, minikube_env, request):
    """
    Parameterized fixture that sets up scrapyd with specified max_proc.
    """
    # Get max_proc from parameter or default to 0
    max_proc = getattr(request, "param", 0)

    # Retrieve a temporary kubernetes yaml with the specified max_proc
    yaml_file = "kubernetes-%d.yaml" % max_proc

    # Now apply the new configuration
    print(f"Applying {yaml_file} with max_proc={max_proc}...")
    subprocess.run(["kubectl", "apply", "-f", yaml_file], check=True, env=minikube_env)

    # Wait for the deployment to be ready
    wait_for_scrapyd_ready()

    # Even after pod is ready, give it a few more seconds to fully initialize
    print("Pod is ready, waiting for internal initialization...")
    time.sleep(3)

    # Port-forward
    pf_proc = subprocess.Popen(
        ["kubectl", "port-forward", "service/scrapyd-k8s", "6800:6800"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    time.sleep(3)

    # Quick health check
    base_url = "http://127.0.0.1:6800"
    try:
        resp = requests.get(f"{base_url}/healthz", timeout=5)
        if resp.status_code != 200:
            pytest.fail("Scrapyd /healthz not OK.")
    except Exception as e:
        pf_proc.terminate()
        pytest.fail(f"Couldn't connect to scrapyd at {base_url}: {e}")

    # Log diagnostics - check the actual configuration
    print("Checking actual config in pod...")
    config_check = subprocess.run(
        ["kubectl", "exec", "deployment/scrapyd-k8s", "--", "cat", "/opt/app/scrapyd_k8s.conf"],
        capture_output=True, text=True
    )
    if config_check.returncode == 0:
        print("Current config in pod:")
        print(config_check.stdout)

        # Highlight the max_proc setting
        if f"max_proc     = {max_proc}" in config_check.stdout:
            print(f"✅ max_proc={max_proc} found in config")
        else:
            print(f"❌ max_proc={max_proc} NOT found in config")

    # Check logs for scheduler initialization
    print("Checking for scheduler initialization in logs...")
    logs = subprocess.run(
        ["kubectl", "logs", "deployment/scrapyd-k8s"],
        capture_output=True, text=True
    )
    if "k8s scheduler started" in logs.stdout.lower():
        print("✅ Scheduler initialization found in logs")
    else:
        print("❌ Scheduler initialization NOT found in logs")

        # Additional diagnostic information
        print("Full pod logs:")
        print(logs.stdout)

    # Print out the environment variables
    print("Checking environment variables:")
    env_vars = subprocess.run(
        ["kubectl", "exec", "deployment/scrapyd-k8s", "--", "env"],
        capture_output=True, text=True
    )
    print(env_vars.stdout)

    yield base_url, max_proc

    # Cleanup
    pf_proc.terminate()
    print(f"Deleting {yaml_file} and cleaning up resources...")
    subprocess.run(["kubectl", "delete", "-f", yaml_file], check=False, env=minikube_env)


def wait_for_job_state(service_url, job_id, target_state, timeout=25):
    """
    Wait until job `job_id` is in `target_state` (one of 'pending', 'running', 'finished') according to listjobs.json.
    Raise TimeoutError if not.
    """
    start = time.time()
    while time.time() - start < timeout:
        r = requests.get(f"{service_url}/listjobs.json")
        data = r.json()
        # data has keys: "pending", "running", "finished"
        for key in ["pending", "running", "finished"]:
            if any(j["id"] == job_id for j in data[key]):
                if key == target_state:
                    return
        time.sleep(2)
    raise TimeoutError(f"Job {job_id} not in {target_state} after {timeout}s")


@pytest.mark.parametrize("scrapyd_service", [0], indirect=True)
def test_zero_allowed_jobs(scrapyd_service):
    """
    With max_proc=0, any scheduled job should remain in the 'pending' state in /listjobs.json
    (i.e., it never goes to 'running' or 'finished').
    """
    service_url, max_proc = scrapyd_service
    print(f"Testing with max_proc={max_proc}")

    # First check the max_proc setting in the pod
    pods = subprocess.run(
        ["kubectl", "get", "pods", "--selector=app.kubernetes.io/name=scrapyd-k8s", "-o", "name"],
        capture_output=True, text=True
    )
    pod_name = pods.stdout.strip()

    if pod_name:
        print(f"Found pod: {pod_name}")
        # Check for the max_proc in logs again
        pod_logs = subprocess.run(
            ["kubectl", "logs", pod_name],
            capture_output=True, text=True
        )
        print("Pod logs related to scheduler:")
        for line in pod_logs.stdout.split('\n'):
            if 'sched' in line.lower() or 'max_proc' in line.lower():
                print(f"  {line.strip()}")
    else:
        print("No pods found for scrapyd-k8s")

    # Schedule a job
    job_id = uuid.uuid4().hex
    resp = requests.post(f"{service_url}/schedule.json", data={
        "project": "example",
        "spider": "quotes",
        "_version": "latest",
        "jobid": job_id
    })
    assert resp.status_code == 200

    # Wait some time, ensure it never leaves "pending"
    # (If your job finishes super fast, you'd never see it running anyway.
    #  So the best we can do is "still pending after X seconds.")
    wait_time = 10
    print(f"Waiting {wait_time}s to confirm job stays pending...")
    time.sleep(wait_time)

    # Check the job is still in 'pending'
    r = requests.get(f"{service_url}/listjobs.json").json()
    pending = [j for j in r["pending"] if j["id"] == job_id]
    running = [j for j in r["running"] if j["id"] == job_id]
    finished = [j for j in r["finished"] if j["id"] == job_id]

    # Check Kubernetes job state
    check_k8s = subprocess.run(
        ["kubectl", "get", "jobs", "--selector=org.scrapy.job_id=" + job_id, "-o", "wide"],
        capture_output=True, text=True
    )
    print(f"Job {job_id} Kubernetes status: {check_k8s.stdout}")

    # Check if the job is suspended
    check_suspended = subprocess.run(
        ["kubectl", "get", "jobs", "--selector=org.scrapy.job_id=" + job_id, "-o",
         "jsonpath='{.items[0].spec.suspend}'"],
        capture_output=True, text=True
    )
    print(f"Job {job_id} suspended state: {check_suspended.stdout}")

    assert len(pending) == 1, (
        f"Expected job {job_id} to remain pending (max_proc=0), got state: {r}"
    )
    assert not running, f"Job {job_id} unexpectedly running: {r}"
    assert not finished, f"Job {job_id} unexpectedly finished: {r}"

    print("test_zero_allowed_jobs passed: job remained pending.")


@pytest.mark.parametrize("scrapyd_service", [1], indirect=True)
def test_one_allowed_job(scrapyd_service):
    """
    With max_proc=1, scheduling two jobs back to back =>
     - The first should move into 'running'
     - The second should remain 'pending' until the first finishes
    """
    service_url, max_proc = scrapyd_service
    print(f"Testing with max_proc={max_proc}")

    # Check for the max_proc in pod
    pods = subprocess.run(
        ["kubectl", "get", "pods", "--selector=app.kubernetes.io/name=scrapyd-k8s", "-o", "name"],
        capture_output=True, text=True
    )
    pod_name = pods.stdout.strip()

    if pod_name:
        print(f"Found pod: {pod_name}")
        # Check for the max_proc in logs again
        pod_logs = subprocess.run(
            ["kubectl", "logs", pod_name],
            capture_output=True, text=True
        )
        print("Pod logs related to scheduler:")
        for line in pod_logs.stdout.split('\n'):
            if 'sched' in line.lower() or 'max_proc' in line.lower():
                print(f"  {line.strip()}")
    else:
        print("No pods found for scrapyd-k8s")

    job1_id = uuid.uuid4().hex
    job2_id = uuid.uuid4().hex

    # Schedule job1
    r1 = requests.post(f"{service_url}/schedule.json", data={
        "project": "example",
        "spider": "quotes",
        "_version": "latest",
        "jobid": job1_id
    })
    assert r1.status_code == 200

    # Schedule job2
    r2 = requests.post(f"{service_url}/schedule.json", data={
        "project": "example",
        "spider": "quotes",
        "_version": "latest",
        "jobid": job2_id
    })
    assert r2.status_code == 200

    # job1 should eventually be 'running'
    print("Waiting for job1 to appear running...")
    wait_for_job_state(service_url, job1_id, 'running', timeout=20)

    # Once job1 is running, job2 should remain 'pending'
    print("Checking job2 is pending while job1 runs...")
    r = requests.get(f"{service_url}/listjobs.json").json()
    pending2 = any(j["id"] == job2_id for j in r["pending"])
    running2 = any(j["id"] == job2_id for j in r["running"])

    # Check Kubernetes job states
    check_job1 = subprocess.run(
        ["kubectl", "get", "jobs", "--selector=org.scrapy.job_id=" + job1_id, "-o", "wide"],
        capture_output=True, text=True
    )
    print(f"Job1 {job1_id} Kubernetes status: {check_job1.stdout}")

    check_job2 = subprocess.run(
        ["kubectl", "get", "jobs", "--selector=org.scrapy.job_id=" + job2_id, "-o", "wide"],
        capture_output=True, text=True
    )
    print(f"Job2 {job2_id} Kubernetes status: {check_job2.stdout}")

    # Check if job2 is suspended
    check_job2_suspended = subprocess.run(
        ["kubectl", "get", "jobs", "--selector=org.scrapy.job_id=" + job2_id, "-o",
         "jsonpath='{.items[0].spec.suspend}'"],
        capture_output=True, text=True
    )
    print(f"Job2 {job2_id} suspended state: {check_job2_suspended.stdout}")

    assert pending2, f"job2 expected pending, got {r}"
    assert not running2, f"job2 is unexpectedly running: {r}"

    # Wait for job1 to finish
    try:
        print("Waiting for job1 to finish...")
        wait_for_job_state(service_url, job1_id, 'finished', timeout=20)
    except TimeoutError as e:
        # if job1 is extremely slow or never finishes, fail
        pytest.fail(str(e))

    # After job1 finishes, job2 should become running
    print("Waiting up to 30s for job2 to become running now that job1 finished...")
    wait_for_job_state(service_url, job2_id, 'running', timeout=25)

    print("test_one_allowed_job passed: concurrency=1 logic is correct.")
