# MegooITAdmin's pending-updates check (backend/app/collector/checks/updates.sh), sent on stdin to `sh -s`. It counts
# pending and security updates without sudo: apt-get -s simulates an upgrade from the lists the server already has,
# and dnf -C reads only its cache, so nothing is downloaded or installed. Read-only.
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
LC_ALL=C
export PATH LC_ALL
if command -v apt-get > /dev/null 2>&1; then
  out=$(timeout 50 apt-get -s -o Debug::NoLocking=1 upgrade 2> /dev/null) || exit 1
  echo '{"status":"ok"}'
  echo 'manager apt'
  printf '%s\n' "$out" | awk '/^Inst / { n++; if (tolower($0) ~ /security/) s++ } END { printf "pending %d\nsecurity %d\n", n, s }'
  if [ -e /var/run/reboot-required ]; then echo 'reboot 1'; else echo 'reboot 0'; fi
  if t=$(stat -c %Y /var/lib/apt/lists 2> /dev/null); then echo "refreshed $t"; fi
elif command -v dnf > /dev/null 2>&1; then
  # -C: only what is cached. dnf never downloads here.
  out=$(timeout 50 dnf check-update -C -q 2> /dev/null); code=$?
  echo '{"status":"ok"}'
  echo 'manager dnf'
  echo "exit $code"
  printf '%s\n' "$out" | awk 'NF == 3 && $1 ~ /\./ { n++ } END { printf "pending %d\n", n }'
  sec=$(timeout 5 dnf updateinfo -C -q list --security 2> /dev/null) && printf '%s\n' "$sec" | awk 'NF >= 3 { n++ } END { printf "security %d\n", n }'
  # Without a cache there is no time: the line is left out, and the script still exits 0.
  if t=$(stat -c %Y /var/cache/dnf 2> /dev/null); then echo "refreshed $t"; fi
else
  echo '{"status":"not_available"}'
fi
