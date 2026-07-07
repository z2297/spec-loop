# Request (verbatim)

Using alpha as the working branch - Udpate the dashboard to be serverd out of a docker
host. When the dashboard is initialized through the terminal it should atempt to start
the container if it is not already running, or if it is attach to the running container.
Live updates from all sessions should be available.

## Clarification (follow-up, verbatim)

It is not claudes job to keep a shell running, it is only the job to start whatever
listener is present. This process should exit when the terminal closes. There should not
be a process leak or drift when the terminal working in the repo closes or ends.
