#!/bin/sh
# Environment preparation for test_joblogs.py (all test configurations).
# Called with "up" argument on setup, with "down" argument afterwards.
#
# Creates the joblogs container paths, as it is required to start scrapyd-k8s.

if [ "$1" = "up" ]; then
  mkdir -p /tmp/joblogs/container/a
  mkdir -p /tmp/joblogs/live
elif [ "$1" = "down" ]; then
  rm -Rf /tmp/joblogs
else
  echo "Usage: $0 up|down"
  exit 1
fi

