#!/bin/sh
# Fresh host keys at every start, then sshd in the foreground as PID 1, logging to stderr (docker logs).
set -e
rm -f /etc/ssh/ssh_host_*
ssh-keygen -A
mkdir -p /run/sshd
exec /usr/sbin/sshd -D -e
