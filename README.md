# Scrapyd for Kubernetes

_Very much a work in progress._

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
  be modified at run-time.

At this moment, each spider job is directly linked to a Docker instance or
Kubernetes job, and the daemon will retrieve its state by looking at those
jobs. Perhaps, in the future, some other job queue mechanism will be used, but
perhaps this is good enough.

Also, no scheduling is happening (yet?), so all jobs created will be started
immediately.

## Docker image

- Spiders are distributed as Docker images.
- One can run `scrapy crawl <spider>` in the container to run a spider,
  without any additional setup (so set `SCRAPY_SETTINGS_MODULE`).
- Each Docker image has specific labels to indicate its project and spiders.
  * `org.scrapy.project` - the project name
  * `org.scrapy.spiders` - the spiders (those returned by `scrapy list`, comma-separated)

For example, you could use this in a Github Action:

```yaml
# ...
jobs:
  container:
    runs-on: ubuntu-latest
    steps:
      - name: Docker meta
        id: meta
        uses: docker/metadata-action@v4
        with: # ...

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v1

      - name: Build
        id: build
        uses: docker/build-push-action@v2
        with:
          push: false
          load: true
          tags: spider:latest

      - name: Get spiders
        if: ${{ github.event_name != 'pull_request' }}
        id: spiders
        run: |
          SPIDERS=`docker run --rm spider:latest scrapy list | tr '\n' ',' | sed 's/,$//'`
          echo "spiders=$SPIDERS" >> "$GITHUB_OUTPUT"

      - name: Rebuild and push
        if: ${{ github.event_name != 'pull_request' }}
        uses: docker/build-push-action@v2
        with:
          push: true
          tags: ${{ steps.meta.outputs.tags }}
          labels: |
            ${{ steps.meta.outputs.labels }}
            org.scrapy.project=CHANGEME
            org.scrapy.spiders=${{ steps.spiders.outputs.spiders }}
```

## Installation

Requirements:
- [Python 3](https://www.python.org/)
- [Skopeo](https://github.com/containers/skopeo) available in `PATH` (for remote repositories)
- Either [Docker](https://www.docker.com/) or [Kubernetes](https://kubernetes.io/) setup and accessible
  (scheduling will require Kubernetes 1.24+)

Copy the configuration `cp scrapyd_k8s.sample.conf scrapyd_k8s.conf` and specify your project details.

TODO finish this section

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

The Docker and Kubernetes launchers have their own additional options.

## License

This software is distributed under the [MIT license](LICENSE.md).
