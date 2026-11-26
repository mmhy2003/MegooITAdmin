# MegooITAdmin's services check (backend/app/collector/checks/services.sh), sent on stdin to `sh -s`. It lists systemd's
# services, loaded or not, one per line: unit, load, active, sub and description. Read-only.
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
LC_ALL=C
export PATH LC_ALL
command -v systemctl > /dev/null 2>&1 || { echo '{"status":"not_available"}'; exit 0; }
echo '{"status":"ok"}'
exec timeout 20 systemctl list-units --type=service --all --plain --no-legend --no-pager
