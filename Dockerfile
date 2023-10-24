FROM python:3.11-slim as base

RUN apt-get update && \
    apt-get install -y --no-install-recommends skopeo && \
    rm -Rf /var/lib/apt/lists/* /var/cache/apt/*

COPY requirements.txt /opt/app/requirements.txt

WORKDIR /opt/app
RUN pip install --no-cache-dir --disable-pip-version-check -r requirements.txt

COPY /scrapyd_k8s/ /opt/app/scrapyd_k8s
COPY /app.py /opt/app/

RUN python -m compileall /opt/app/scrapyd_k8s

# TODO make it work with a regular user
#USER nobody
EXPOSE 6800

WORKDIR /opt/app

ENV PYTHONPATH=/opt/app/

CMD ["python3", "/opt/app/app.py"]
