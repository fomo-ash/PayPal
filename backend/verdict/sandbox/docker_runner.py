"""Docker + gVisor fallback runner.

docker run --rm --runtime=runsc --network none --read-only --tmpfs /tmp:size=16m
  --memory 512m --cpus 1 --pids-limit 64 --user 65534:65534 --cap-drop ALL
  --security-opt no-new-privileges -v <submission>:/work/submission:ro
  -v <harness.py>:/work/harness.py:ro  python:3.12-slim
  python -I /work/harness.py /work/submission solution solve
Runs on a separate VM (Fly.io / Hetzner): Render cannot run Docker-in-Docker.
"""
