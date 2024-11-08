# Scrapyd for Kubernetes

Scrapyd-k8s is an application for deploying and running Scrapy spiders as
either Docker instances or Kubernetes jobs. Its intention is to be compatible
with [scrapyd](https://scrapyd.readthedocs.io/), but adapt to a container-based
environment.

There are some important differences, though:

* _Spiders are distributed as Docker images_, not as Python eggs. This allows
  to bundle spiders with dependencies, with all its benefits (and downsides).

* _Each spider is run as a Docker instance or Kubernetes job_, instead of a process.
  This gives good visibility within an already running cluster.

* _Projects are specified in the configuration file_, which means this can not
  be modified at run-time. On the other hand, scrapyd-k8s can be restarted
  without affecting any running spiders.

At this moment, each spider job is directly linked to a Docker instance or
Kubernetes job, and the daemon will retrieve its state by looking at those
jobs. This makes it easy to inspect and adjust the spider queue even outside
scrapyd-k8s.

No scheduling is happening (yet?), so all jobs created will be started immediately.

## Running

Typically this application will be run on using a (Docker or Kubernetes) container.
You will need to provide a configuration file, use one of the sample configuration
files as a template ([`scrapyd_k8s.sample-k8s.conf`](./scrapyd_k8s.sample-k8s.conf)
or [`scrapyd_k8s.sample-docker.conf`](./scrapyd_k8s.sample-docker.conf)).

The next section explains how to get this running Docker, Kubernetes or Local.
Then read on for an example of how to use the API.

### Docker

```
cp scrapyd_k8s.sample-docker.conf scrapyd_k8s.conf
docker build -t ghcr.io/q-m/scrapyd-k8s:latest .
docker run \
  --rm \
  -v ./scrapyd_k8s.conf:/opt/app/scrapyd_k8s.conf:ro \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v $HOME/.docker/config.json:/root/.docker/config.json:ro \
  -u 0 \
  -p 127.0.0.1:6800:6800 \
  ghcr.io/q-m/scrapyd-k8s:latest
```

You'll be able to talk to localhost on port `6800`.

Make sure to pull the spider image so it is known locally.
In case of the default example spider:

```sh
docker pull ghcr.io/q-m/scrapyd-k8s-spider-example
```

Note that running like this in Docker is not really recommended for production,
as it exposes the Docker socket and runs as root. It may be useful to try
things out.


### Kubernetes

1. Adapt the spider configuration in [`kubernetes.yaml`](./kubernetes.yaml) (`scrapyd_k8s.conf` in configmap)
2. Create the resources: `kubectl create -f kubernetes.yaml`

You'll be able to talk to the `scrapyd-k8s` service on port `6800`.

### Local

For development, or just a quick start, you can also run this application locally.

Requirements:
- [Python 3](https://www.python.org/)
- [Skopeo](https://github.com/containers/skopeo) available in `PATH` (for remote repositories)
- Either [Docker](https://www.docker.com/) or [Kubernetes](https://kubernetes.io/) setup and accessible
  (scheduling will require Kubernetes 1.24+)

This will work with either Docker or Kubernetes (provided it is setup).
For example, for Docker:

```sh
cp scrapyd_k8s.sample-docker.conf scrapyd_k8s.conf
python3 -m scrapyd_k8s
```

You'll be able to talk to localhost on port `6800`.

For Docker, make sure to pull the spider image so it is known locally.
In case of the default example spider:

```sh
docker pull ghcr.io/q-m/scrapyd-k8s-spider-example
```


## Accessing the API

With `scrapyd-k8s` running and setup, you can access it. Here we assume that
it listens on `localhost:6800` (for Kubernetes, you would use
the service name `scrapyd-k8s:6800` instead).

```sh
curl http://localhost:6800/daemonstatus.json
```

> ```json
> {"spiders":0,"status":"ok"}
> ```

```sh
curl http://localhost:6800/listprojects.json
```

> ```json
> {"projects":["example"],"status":"ok"}
> ```

```sh
curl 'http://localhost:6800/listversions.json?project=example'
```

> ```json
> {"status":"ok","versions":["latest"]}
> ```

```sh
curl 'http://localhost:6800/listspiders.json?project=example&_version=latest'
```

> ```json
> {"spiders":["quotes","static"],"status":"ok"}
> ```

```sh
curl -F project=example -F _version=latest -F spider=quotes http://localhost:6800/schedule.json
```

> ```json
> {"jobid":"e9b81fccbec211eeb3b109f30f136c01","status":"ok"}
> ```

```sh
curl http://localhost:6800/listjobs.json
```
```json
{
  "finished":[],
  "pending":[],
  "running":[{"id":"e9b81fccbec211eeb3b109f30f136c01","project":"example","spider":"quotes","state":"running", "start_time":"2012-09-12 10:14:03.594664", "end_time":null}],
  "status":"ok"
}
```

To see what the spider has done, look at the container logs:

```sh
docker ps -a
```

> ```
> CONTAINER ID  IMAGE                                          COMMAND                CREATED   STATUS              NAMES
> 8c514a7ac917  ghcr.io/q-m/scrapyd-k8s-spider-example:latest  "scrapy crawl quotes"  42s ago   Exited (0) 30s ago  scrapyd_example_cb50c27cbec311eeb3b109f30f136c01
> ```

```sh
docker logs 8c514a7ac917
```

> ```
> [scrapy.utils.log] INFO: Scrapy 2.11.0 started (bot: example)
> ...
> [scrapy.core.scraper] DEBUG: Scraped from <200 http://quotes.toscrape.com/>
> {'text': 'The world as we have created it is a process of our thinking. It cannot be changed without changing our thinking.', 'author': 'Albert Einstein', 'tags': 'change'}
> ...
> [scrapy.core.engine] INFO: Spider closed (finished)
> ```


## Spider as Docker image

- Spiders are distributed as Docker images.
- One can run `scrapy crawl <spider>` in the container to run a spider,
  without any additional setup (so set `SCRAPY_SETTINGS_MODULE`).
- Each Docker image has specific labels to indicate its project and spiders.
  * `org.scrapy.project` - the project name
  * `org.scrapy.spiders` - the spiders (those returned by `scrapy list`, comma-separated)

An example spider is available at [q-m/scrapyd-k8s-example-spider](https://github.com/q-m/scrapyd-k8s-spider-example),
including a [Github Action](https://github.com/q-m/scrapyd-k8s-spider-example/blob/main/.github/workflows/container.yml) for building a container.


## API

### `daemonstatus.json` ([➽](https://scrapyd.readthedocs.io/en/latest/api.html#daemonstatus-json))

Lists scrapyd jobs by looking at Docker containers or Kubernetes jobs.

### ~~`addversion.json`~~ ([➽](https://scrapyd.readthedocs.io/en/latest/api.html#addversion-json))

Not supported, by design.
If you want to add a version, add a Docker image to the repository.

### `schedule.json` ([➽](https://scrapyd.readthedocs.io/en/latest/api.html#schedule-json))

Schedules a new spider by creating a Docker container or Kubernetes job.

### `cancel.json` ([➽](https://scrapyd.readthedocs.io/en/latest/api.html#cancel-json))

Removes a scheduled spider, kills it when running, does nothing when finished.

### `listprojects.json` ([➽](https://scrapyd.readthedocs.io/en/latest/api.html#listprojects-json))

Lists projects from the configuration file.

### `listversions.json` ([➽](https://scrapyd.readthedocs.io/en/latest/api.html#listversions-json))

Lists versions from the project's Docker repository.

### `listspiders.json` ([➽](https://scrapyd.readthedocs.io/en/latest/api.html#listspiders-json))

Lists spiders from the spider image's `org.scrapy.spiders` label.

### `listjobs.json` ([➽](https://scrapyd.readthedocs.io/en/latest/api.html#listjobs-json))

Lists current jobs by looking at Docker containers or Kubernetes jobs.

* **End time**: Set only for completed Kubernetes jobs; always null for Docker.

### ~~`delversion.json`~~ ([➽](https://scrapyd.readthedocs.io/en/latest/api.html#delversion-json))

Not supported, by design.
If you want to delete a version, remove the corresponding Docker image from the repository.

### ~~`delproject.json`~~ ([➽](https://scrapyd.readthedocs.io/en/latest/api.html#delproject-json))

Not supported, by design.
If you want to delete a project, remove it from the configuration file.

## Configuration file

* `http_port`    - defaults to `6800` ([➽](https://scrapyd.readthedocs.io/en/latest/config.html#http-port))
* `bind_address` - defaults to `127.0.0.1` ([➽](https://scrapyd.readthedocs.io/en/latest/config.html#bind-address))
* `max_proc`     - _(implementation pending)_, if unset or `0` it will use the number of nodes in the cluster, defaults to `0` ([➽](https://scrapyd.readthedocs.io/en/latest/config.html#max-proc))
* `repository`   - Python class for accessing the image repository, defaults to `scrapyd_k8s.repository.Remote`
* `launcher`     - Python class for managing jobs on the cluster, defaults to `scrapyd_k8s.launcher.K8s`
* `username`     - Set this and `password` to enable basic authentication ([➽](https://scrapyd.readthedocs.io/en/latest/config.html#username))
* `password`     - Set this and `username` to enable basic authentication ([➽](https://scrapyd.readthedocs.io/en/latest/config.html#password))

The Docker and Kubernetes launchers have their own additional options.

## License

This software is distributed under the [MIT license](LICENSE.md).
