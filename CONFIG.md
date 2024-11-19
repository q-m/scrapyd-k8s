## About
This file provides you with the detailed description of parameters listed in the config file, and explaining why they are used
and when you are expected to provide or change them.

## [scrapyd] section, reconnection_attempts, backoff_time, backoff_coefficient

### Context
The Kubernetes event watcher is used in the code as part of the joblogs feature and is also utilized for limiting the 
number of jobs running in parallel on the cluster. Both features are not enabled by default and can be activated if you 
choose to use them.

The event watcher establishes a connection to the Kubernetes API and receives a stream of events from it. However, the 
nature of this long-lived connection is unstable; it can be interrupted by network issues, proxies configured to terminate 
long-lived connections, and other factors. For this reason, a mechanism was implemented to re-establish the long-lived 
connection to the Kubernetes API. To achieve this, three parameters were introduced: `reconnection_attempts`, 
`backoff_time` and `backoff_coefficient`.

### What are these parameters about?
- `reconnection_attempts` - defines how many consecutive attempts will be made to reconnect if the connection fails;
- `backoff_time` and `backoff_coefficient` - are used to gradually slow down each subsequent attempt to establish a 
connection with the Kubernetes API, preventing the API from becoming overloaded with requests. The `backoff_time` increases 
exponentially and is calculated as `backoff_time *= self.backoff_coefficient`.

### When do I need to change it in the config file?
Default values for these parameters are provided in the code and are tuned to an "average" cluster setting. If your network 
requirements or other conditions are unusual, you may need to adjust these values to better suit your specific setup.