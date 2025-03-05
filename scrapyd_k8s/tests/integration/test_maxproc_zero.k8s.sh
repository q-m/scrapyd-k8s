#!/bin/sh
# Kubernetes cluster preparation for test_maxproc_zero.py
# Called with "up" argument on setup, with "down" argument afterwards.
#
# Adds "patch" to job role permissions.
# Tightly bound to kubernetes.yaml

if [ "$1" = "up" ]; then
  kubectl patch role scrapyd-k8s --type=json -p='[
    {
      "op": "add",
      "path": "/rules/3/verbs/0",
      "value": "patch"
    }
  ]'
elif [ "$1" = "down" ]; then
  kubectl patch role scrapyd-k8s --type=json -p='[
    {
      "op": "remove",
      "path": "/rules/3/verbs/0"
    }
  ]'
else
  echo "Usage: $0 up|down"
  exit 1
fi
