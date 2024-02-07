FROM python:3.11-slim as base

RUN apt-get update && \
    apt-get install -y --no-install-recommends skopeo && \
    rm -Rf /var/lib/apt/lists/* /var/cache/apt/*

WORKDIR /opt/app

COPY requirements.txt .

RUN pip install --no-cache-dir --disable-pip-version-check -r requirements.txt

COPY scrapyd_k8s/ scrapyd_k8s/

RUN python -m compileall ./scrapyd_k8s

USER nobody
EXPOSE 6800

ENV PYTHONPATH=/opt/app/
ENV PYTHONUNBUFFERED=1

CMD ["python3", "-m", "scrapyd_k8s"]
