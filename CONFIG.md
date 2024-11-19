# scrapyd-k8s configuration

scrapyd-k8s is configured with the file `scrapyd_k8s.conf`. The file format is meant to
stick to [scrapyd's configuration](https://scrapyd.readthedocs.io/en/latest/config.html) where possible.

## `[scrapyd]` section

* `http_port`    - defaults to `6800` ([➽](https://scrapyd.readthedocs.io/en/latest/config.html#http-port))
* `bind_address` - defaults to `127.0.0.1` ([➽](https://scrapyd.readthedocs.io/en/latest/config.html#bind-address))
* `max_proc`     - _(implementation pending)_, if unset or `0` it will use the number of nodes in the cluster, defaults to `0` ([➽](https://scrapyd.readthedocs.io/en/latest/config.html#max-proc))
* `repository`   - Python class for accessing the image repository, defaults to `scrapyd_k8s.repository.Remote`
* `launcher`     - Python class for managing jobs on the cluster, defaults to `scrapyd_k8s.launcher.K8s`
* `username`     - Set this and `password` to enable basic authentication ([➽](https://scrapyd.readthedocs.io/en/latest/config.html#username))
* `password`     - Set this and `username` to enable basic authentication ([➽](https://scrapyd.readthedocs.io/en/latest/config.html#password))

The Docker and Kubernetes launchers have their own additional options.

## project sections

Each project you want to be able to run, gets its own section, prefixed with `project.`. For example,
consider an `example` spider, this would be defined in a `[project.example]` section.

* `repository` - container repository for the project, e.g. `ghcr.io/q-m/scrapyd-k8s-spider-example`

## Docker

This section describes Docker-specific options.
See [`scrapyd_k8s.sample-docker.conf`](scrapyd_k8s.sample-docker.conf) for an example.

* `[scrapyd]` `launcher` - set this to `scrapyd_k8s.launcher.Docker`
* `[scrapyd]` `repository` - choose between `scrapyd_k8s.repository.Local` and `scrapyd_k8s.repository.Remote`

TODO: explain `Local` and `Remote` repository, and how to use them

## Kubernetes

This section describes Kubernetes-specific options.
See [`scrapyd_k8s.sample-k8s.conf`](scrapyd_k8s.sample-k8s.conf) for an example.

* `[scrapyd]` `launcher` - set this to `scrapyd_k8s.launcher.K8s`
* `[scrapyd]` `repository` - set this to `scrapyd_k8s.repository.Remote`

For Kubernetes, it is important to set resource limits.

TODO: explain how to set limits, with default, project and spider specificity.


### Kubernetes API interaction

The Kubernetes event watcher is used in the code as part of the joblogs feature and is also utilized for limiting the
number of jobs running in parallel on the cluster. Both features are not enabled by default and can be activated if you
choose to use them.

The event watcher establishes a connection to the Kubernetes API and receives a stream of events from it. However, the
nature of this long-lived connection is unstable; it can be interrupted by network issues, proxies configured to terminate
long-lived connections, and other factors. For this reason, a mechanism was implemented to re-establish the long-lived
connection to the Kubernetes API. To achieve this, three parameters were introduced: `reconnection_attempts`,
`backoff_time` and `backoff_coefficient`.

#### What are these parameters about?

* `reconnection_attempts` - defines how many consecutive attempts will be made to reconnect if the connection fails;
* `backoff_time`, `backoff_coefficient` - are used to gradually slow down each subsequent attempt to establish a
  connection with the Kubernetes API, preventing the API from becoming overloaded with requests.
  The `backoff_time` increases exponentially and is calculated as `backoff_time *= self.backoff_coefficient`.

#### When do I need to change it in the config file?

Default values for these parameters are provided in the code and are tuned to an "average" cluster setting. If your network
requirements or other conditions are unusual, you may need to adjust these values to better suit your specific setup.

