import threading
import logging
import time
from kubernetes import client, watch
from typing import Callable, List

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

    def __init__(self, namespace: str):
        """
        Initializes the ResourceWatcher.

        Parameters
        ----------
        namespace : str
            Kubernetes namespace to watch pods in.
        """
        self.namespace = namespace
        self.subscribers: List[Callable] = []
        self._stop_event = threading.Event()
        self.watcher_thread = threading.Thread(target=self.watch_pods, daemon=True)
        self.watcher_thread.start()
        logger.info(f"ResourceWatcher thread started for namespace '{self.namespace}'.")

    def subscribe(self, callback: Callable):
        """
        Adds a subscriber callback to be notified on events.

        Parameters
        ----------
        callback : Callable
            A function to call when an event is received.
        """
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

        logger.info(f"Started watching pods in namespace '{self.namespace}'.")

        while not self._stop_event.is_set():
            try:
                for event in w.stream(v1.list_namespaced_pod, namespace=self.namespace, timeout_seconds=0):
                    pod_name = event['object'].metadata.name
                    event_type = event['type']
                    logger.debug(f"Received event: {event_type} for pod: {pod_name}")
                    self.notify_subscribers(event)
            except Exception as e:
                logger.exception(f"Error watching pods in namespace '{self.namespace}': {e}")
                logger.info("Retrying to watch pods after a short delay...")
                time.sleep(5)

    def stop(self):
        """
        Stops the watcher thread gracefully.
        """
        self._stop_event.set()
        self.watcher_thread.join()
        logger.info(f"ResourceWatcher thread stopped for namespace '{self.namespace}'.")
