#!/bin/sh
# Kubernetes cluster preparation for test_joblogs_gzip.py
# Called with "up" argument on setup, with "down" argument afterwards.
#
# Creates the joblogs container path before starting the pod.
# Tightly bound to kubernetes.yaml
# Assumes no minikind mounts are active.
# Assumes scrapy container runs as user nobody (uid 65534).

if [ "$1" = "up" ]; then
  mkdir -p /tmp/joblogs/container/a
  mkdir -p /tmp/joblogs/live
  minikube mount /tmp/joblogs:/tmp/joblogs --uid=65534 &
  kubectl patch deploy scrapyd-k8s --type=json -p='[
    {
      "op": "add",
      "path": "/spec/template/spec/volumes/0",
      "value": {
        "name": "joblogs",
        "hostPath": {
          "path": "/tmp/joblogs"
        }
      }
    },
    {
      "op": "add",
      "path": "/spec/template/spec/containers/0/volumeMounts/0",
      "value": {
        "mountPath": "/tmp/joblogs",
        "name": "joblogs"
      }
    }
  ]'
elif [ "$1" = "down" ]; then
  kubectl patch deploy scrapyd-k8s --type=json -p='[
    {
      "op": "remove",
      "path": "/spec/template/spec/containers/0/volumeMounts/0"
    },
    {
      "op": "remove",
      "path": "/spec/template/spec/volumes/0"
    }
  ]'
  minikube mount --kill=true
  rm -Rf /tmp/joblogs
else
  echo "Usage: $0 up|down"
  exit 1
fi
