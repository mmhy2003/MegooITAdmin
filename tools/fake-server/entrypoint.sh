#!/bin/sh
# New host keys at the container's first start, kept when it restarts (swap-host-key still changes them on purpose),
# then sshd in the foreground as PID 1, logging to stderr (docker logs).
set -e
if [ ! -e /etc/ssh/.megoo-host-keys ]; then
  rm -f /etc/ssh/ssh_host_*
  ssh-keygen -A
  touch /etc/ssh/.megoo-host-keys
fi
mkdir -p /run/sshd
exec /usr/sbin/sshd -D -e
