# MegooITAdmin's containers check (backend/app/collector/checks/containers.sh), sent on stdin to `sh -s`. It lists
# Docker's containers through megoo-ctl, the only command the platform's account may run with sudo. Read-only.
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
LC_ALL=C
export PATH LC_ALL
CTL=/usr/local/sbin/megoo-ctl
command -v docker > /dev/null 2>&1 || { echo '{"status":"not_available"}'; exit 0; }
timeout 5 sudo -n "$CTL" version > /dev/null 2>&1 || { echo '{"status":"denied"}'; exit 0; }
echo '{"status":"ok"}'
# megoo-ctl runs docker ps --all --no-trunc --format '{{json .}}': one JSON object per line.
exec timeout 20 sudo -n "$CTL" docker ps
