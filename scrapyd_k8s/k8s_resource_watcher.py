import logging
import threading
import time
from kubernetes import client, watch
from typing import Callable, List
import urllib3

logger = logging.getLogger(__name__)

class ResourceWatcher:
    """
    Watches Kubernetes pod events and notifies subscribers about relevant events.

    Attributes
    ----------
    namespace : str
        Kubernetes namespace to watch pods in.
    subscribers : List[Callable]
        List of subscriber callback functions to notify on events.
    """
    def __init__(self, namespace, config):
        """
        Initializes the ResourceWatcher.

        Parameters
        ----------
        namespace : str
            Kubernetes namespace to watch pods in.
        """
        self.namespace = namespace
        self.backoff_time = int(config.scrapyd().get('backoff_time', 5))
        self.backoff_coefficient = int(config.scrapyd().get('backoff_coefficient', 2))
        self.subscribers: List[Callable] = []
        self._stop_event = threading.Event()
        self.watcher_thread = threading.Thread(target=self.watch_pods, daemon=True)
        self.watcher_thread.start()
        self._lock = threading.Lock()
        logger.info(f"ResourceWatcher thread started for namespace '{self.namespace}'.")

    def subscribe(self, callback: Callable):
        """
        Adds a subscriber callback to be notified on events.

        Parameters
        ----------
        callback : Callable
            A function to call when an event is received.
        """
        with self._lock:
            if callback not in self.subscribers:
                self.subscribers.append(callback)
                logger.debug(f"Subscriber {callback.__name__} added.")
    def unsubscribe(self, callback: Callable):
        """
        Removes a subscriber callback.

        Parameters
        ----------
        callback : Callable
            The subscriber function to remove.
        """
        with self._lock:
            if callback in self.subscribers:
                self.subscribers.remove(callback)
                logger.debug(f"Subscriber {callback.__name__} removed.")
    def notify_subscribers(self, event: dict):
        """
        Notifies all subscribers about an event.

        Parameters
        ----------
        event : dict
            The Kubernetes event data.
        """
        with self._lock:
            for subscriber in self.subscribers:
                try:
                    subscriber(event)
                except Exception as e:
                    logger.exception(f"Error notifying subscriber {subscriber.__name__}: {e}")

    def watch_pods(self):
        """
        Watches Kubernetes pod events and notifies subscribers.
        Runs in a separate thread.
        """
        v1 = client.CoreV1Api()
        w = watch.Watch()
        resource_version = None

        logger.info(f"Started watching pods in namespace '{self.namespace}'.")
        backoff_time = self.backoff_time
        while not self._stop_event.is_set():
            try:
                kwargs = {
                    'namespace': self.namespace,
                    'timeout_seconds': 0,
                }
                if resource_version:
                    kwargs['resource_version'] = resource_version
                first_event = True
                for event in w.stream(v1.list_namespaced_pod, **kwargs):
                    logging.debug("Connected to the k8s API, received an event from k8s API")
                    if first_event:
                        # Reset reconnection attempts and backoff time upon successful reconnection
                        logging.debug("This is the first event in the stream in the established connection, setting reconnection attempts to default")
                        backoff_time = self.backoff_time
                        first_event = False  # Ensure this only happens once per connection
                    pod_name = event['object'].metadata.name
                    resource_version = event['object'].metadata.resource_version
                    event_type = event['type']
                    logger.debug(f"Received event: {event_type} for pod: {pod_name}")
                    self.notify_subscribers(event)
            except (urllib3.exceptions.ProtocolError,
                    urllib3.exceptions.ReadTimeoutError,
                    urllib3.exceptions.ConnectionError) as e:
                logger.exception(f"Encountered network error: {e}")
                logger.info(f"Retrying to watch pods after {backoff_time} seconds...")
                time.sleep(backoff_time)
                backoff_time = min(backoff_time*self.backoff_coefficient, 900)
            except client.ApiException as e:
                # Resource version is too old and cannot be accessed anymore
                if e.status == 410:
                    logger.error("Received 410 Gone error, resetting resource_version and restarting watch.")
                    resource_version = None
                    continue
                else:
                    logger.exception(f"Encountered ApiException: {e}")
                    logger.info(f"Retrying to watch pods after {backoff_time} seconds...")
                    time.sleep(backoff_time)
                    backoff_time = min(backoff_time*self.backoff_coefficient, 900)
            except StopIteration:
                logger.info("Watch stream ended, restarting watch.")
                continue
            except Exception as e:
                logger.exception(f"Watcher encountered exception: {e}")
                logger.info(f"Retrying to watch pods after {backoff_time} seconds...")
                time.sleep(backoff_time)
                backoff_time = min(backoff_time*self.backoff_coefficient, 900)

    def stop(self):
        """
        Stops the watcher thread gracefully.
        """
        self._stop_event.set()
        self.watcher_thread.join()
        logger.info(f"ResourceWatcher thread stopped for namespace '{self.namespace}'.")
