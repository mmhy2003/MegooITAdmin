# MegooITAdmin's failed-logins check (backend/app/collector/checks/logins.sh), sent on stdin to `sh -s`. It reads sshd's
# journal of the last 24 hours (megoo is in the systemd-journal group) and counts failed sign-ins on the server: only a
# count and source addresses leave it, never a user name. Read-only.
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
LC_ALL=C
export PATH LC_ALL
command -v journalctl > /dev/null 2>&1 || { echo '{"status":"not_available"}'; exit 0; }
# The address is the word after the LAST " from ": the user name before it is the attacker's text.
COUNT='
function source(line,   rest, j) { rest = ""; while ((j = index(line, " from ")) > 0) { line = substr(line, j + 6); rest = line }; split(rest, w, " "); return w[1] }
/^Failed password for invalid user / { next }
/^Failed password for / || /^Invalid user / { n++; a = source($0); if (a != "") c[a]++ }
END { printf "total %d\n", n; for (a in c) printf "%d %s\n", c[a], a }'
counts=$(timeout 30 journalctl -q --no-pager -o cat --since=-24h -t sshd -t sshd-session 2> /dev/null | awk "$COUNT")
echo '{"status":"ok"}'
printf '%s\n' "$counts" | grep '^total '
printf '%s\n' "$counts" | grep -v '^total ' | sort -rn | head -n 20
