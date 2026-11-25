# MegooITAdmin's top-processes check (backend/app/collector/checks/processes.sh), sent on stdin to `sh -s`. It reads
# /proc/<pid>/stat twice, one second apart, and runs ps for the user, the resident memory and the name. Read-only.
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
LC_ALL=C
export PATH LC_ALL
command -v ps > /dev/null 2>&1 || { echo '{"status":"not_available"}'; exit 0; }
# pid and utime + stime: the name in parentheses may hold spaces, so the fields are counted after the last ") ".
TICKS='{ s = $0; sub(/^.*\) /, "", s); split(s, f, " "); print $1, f[12] + f[13] }'
first=$(cat /proc/[0-9]*/stat 2> /dev/null | awk "$TICKS")
sleep 1
hz=$(getconf CLK_TCK 2> /dev/null) || hz=100
echo '{"status":"ok"}'
printf '{"hz":%s}\n' "$hz"
{
  printf '%s\n' "$first" | sed 's/^/A /'
  cat /proc/[0-9]*/stat 2> /dev/null | awk "$TICKS" | sed 's/^/B /'
  timeout 10 ps -e -o pid=,user:32=,rss=,comm= | sed 's/^ */P /'
} | awk '
$1 == "A" { a[$2] = $3; next }
$1 == "B" { b[$2] = $3; next }
$1 == "P" && ($2 in b) { name = $0; sub(/^P +[0-9]+ +[^ ]+ +[0-9]+ /, "", name)
  printf "%s\t%s\t%d\t%s\t%s\n", $2, $3, b[$2] - (($2 in a) ? a[$2] : 0), $4, name }'
