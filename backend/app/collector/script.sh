# MegooITAdmin's metrics loop (backend/app/collector/script.sh). The collector sends it on stdin to `sh -s <interval>`
# as the server's account: it reads /proc and runs df on local filesystems only, needs no privilege and writes no file. It
# prints one JSON line every <interval> seconds and ends when its output closes.
set -f
interval=$1
case $interval in [1-9]|10) ;; *) echo 'usage: sh -s <1-10>' >&2; exit 2 ;; esac

# Local filesystems only, so a hung network mount cannot stall the loop. Escaped names (\040 …) are skipped.
MOUNTS='($3 ~ /^(ext2|ext3|ext4|xfs|btrfs|f2fs|jfs|vfat|exfat)$/ || ($3 == "overlay" && $2 == "/")) && $2 !~ /\\/ && !seen[$2]++ && n++ < 64 { print $2 }'

SAMPLE='
function s(x) { return x ~ /^[0-9]+$/ ? x : "0" }
function d(x) { return x ~ /^[0-9]+(\.[0-9]+)?$/ ? x : "0" }
function q(x,   i, c, o) { o = ""; for (i = 1; i <= length(x); i++) { c = substr(x, i, 1); if (c == "\\" || c == "\"") o = o "\\" c; else if (c >= " ") o = o c }; return "\"" o "\"" }
function add(list, item) { return list == "" ? item : list "," item }
FNR == 1 { f++ }
f == 1 { up = d($1) }
f == 2 && $1 ~ /^cpu[0-9]*$/ && ncpu++ < 257 { cpu = add(cpu, "[" q($1) "," s($2) "," s($3) "," s($4) "," s($5) "," s($6) "," s($7) "," s($8) "," s($9) "]") }
f == 3 { load = d($1) "," d($2) "," d($3) }
f == 4 { m[$1] = $2 }
f == 5 && FNR > 2 { i = index($0, ":"); name = substr($0, 1, i - 1); gsub(/ /, "", name); split(substr($0, i + 1), a, " ")
  if (name != "lo" && name !~ /^veth/ && length(name) <= 255 && nnet++ < 64) net = add(net, "[" q(name) "," s(a[1]) "," s(a[9]) "]") }
f == 6 && $3 ~ /^(sd[a-z]+|vd[a-z]+|xvd[a-z]+|hd[a-z]+|nvme[0-9]+n[0-9]+|mmcblk[0-9]+)$/ && ndisk++ < 64 { disk = add(disk, "[" q($3) "," s($6) "," s($10) "," s($13) "]") }
f == 7 && $1 == "#K" { part = "k"; next }
f == 7 && $1 == "#I" { part = "i"; next }
f == 7 && $1 != "Filesystem" && NF >= 6 && part == "k" { mt = $NF; if (!(mt in size)) order[++nfs] = mt; size[mt] = s($(NF-4)); used[mt] = s($(NF-3)); avail[mt] = s($(NF-2)) }
f == 7 && $1 != "Filesystem" && NF >= 6 && part == "i" { ino[$NF] = s($(NF-4)); iused[$NF] = s($(NF-3)) }
END {
  for (k = 1; k <= nfs; k++) { mt = order[k]; fs = add(fs, "[" q(mt) "," size[mt] "," used[mt] "," avail[mt] "," s(ino[mt]) "," s(iused[mt]) "]") }
  printf "{\"v\":1,\"uptime\":%s,\"load\":[%s],\"cpu\":[%s],\"mem\":{\"total\":%s,\"available\":%s,\"swap_total\":%s,\"swap_free\":%s},\"net\":[%s],\"disk\":[%s],\"fs\":[%s]}\n", up, load, cpu, s(m["MemTotal:"]), s(m["MemAvailable:"]), s(m["SwapTotal:"]), s(m["SwapFree:"]), net, disk, fs
}'

while :; do
  set -- $(awk "$MOUNTS" /proc/mounts)
  {
    if [ $# -gt 0 ]; then echo '#K'; df -kP -- "$@"; echo '#I'; df -iP -- "$@"; fi
  } 2>/dev/null </dev/null | awk "$SAMPLE" /proc/uptime /proc/stat /proc/loadavg /proc/meminfo /proc/net/dev /proc/diskstats - || exit 0
  sleep "$interval" || exit 0
done
