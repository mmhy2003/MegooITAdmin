#!/bin/sh
# megoo-setup.sh: prepares a Linux server for MegooITAdmin. Run it as root:
#   sh megoo-setup.sh --from <addresses> --key '<public key line>' [--user <name>]
#   sh megoo-setup.sh --check [--user <name>]
# It creates the account (megoo by default), puts it in systemd-journal and adm and never in docker, installs
# /usr/local/sbin/megoo-ctl and the one sudo rule that allows it, and accepts the platform's key only from the given
# addresses. Then it checks all of that. --check only checks and changes nothing. It installs no packages and
# changes no firewall or sshd setting. Exit: 0 ready, 1 a check failed, 2 refused before any change.
# See docs/server-setup.md.
set -eu
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
LC_ALL=C
export PATH LC_ALL
umask 022

CTL_VERSION=1
CTL=/usr/local/sbin/megoo-ctl
NL='
'

usage() {
  echo "Usage: sh megoo-setup.sh --from <addresses> --key '<public key line>' [--user <name>]" >&2
  echo "       sh megoo-setup.sh --check [--user <name>]" >&2
  exit 2
}
stop() { echo "megoo-setup: $1 Nothing was changed." >&2; exit 2; }

user=megoo from= key= check=
while [ $# -gt 0 ]; do
  case "$1" in
    --from) [ $# -ge 2 ] || usage; from=$2; shift 2 ;;
    --key) [ $# -ge 2 ] || usage; key=$2; shift 2 ;;
    --user) [ $# -ge 2 ] || usage; user=$2; shift 2 ;;
    --check) check=1; shift ;;
    *) usage ;;
  esac
done

# 1. Everything is checked before anything changes.
[ "$(id -u)" = 0 ] || stop "Run it as root: sudo sh megoo-setup.sh …"
for tool in sudo visudo useradd usermod gpasswd getent ssh-keygen stat cmp mktemp; do
  command -v "$tool" > /dev/null 2>&1 || stop "$tool is missing: install it first."
done
getent group systemd-journal > /dev/null || stop "The group systemd-journal is missing: the server needs systemd."
getent group adm > /dev/null || stop "The group adm is missing."
[ -d /etc/sudoers.d ] || stop "/etc/sudoers.d is missing."
case "$user" in
  root) stop "The account may not be root." ;;
  ''|[!a-z_]*|*[!a-z0-9_-]*) stop "Not an account name: $user (use a-z, 0-9, _ and -)." ;;
esac
[ ${#user} -le 32 ] || stop "Not an account name: $user (32 characters at most)."
if getent passwd "$user" > /dev/null && [ "$(id -u "$user")" = 0 ]; then
  stop "$user has uid 0: use an account that is not root."
fi
if [ -z "$check" ]; then
  [ -n "$from" ] || stop "--from is required: the platform's address, for example --from 203.0.113.10."
  case "$from" in
    *[!A-Za-z0-9.:/,*?!-]*) stop "--from may hold only addresses, ranges, host names, * ? ! and commas." ;;
  esac
  [ -n "$key" ] || stop "--key is required: the platform's public key line, from the server page."
  case "$key" in
    *"$NL"*|*\"*|*\'*) stop "--key must be one public key line." ;;
    ssh-ed25519\ *|ssh-rsa\ *|ecdsa-sha2-*\ *|sk-*\ *) ;;
    *) stop "--key must start with the key type, such as ssh-ed25519." ;;
  esac
  keyfile=$(mktemp)
  printf '%s\n' "$key" > "$keyfile"
  if ! ssh-keygen -l -f "$keyfile" > /dev/null 2>&1; then rm -f "$keyfile"; stop "--key is not a public key."; fi
  rm -f "$keyfile"
fi

changed=
say() { echo "$1"; changed=1; }
in_group() { id -Gn "$1" | tr ' ' '\n' | grep -qx "$2"; }

# write_file <path> <owner> <group> <mode> <tmp>: moves tmp into place, unless the path already holds the same
# content with that owner and mode.
write_file() {
  if [ -f "$1" ] && cmp -s "$5" "$1" && [ "$(stat -c '%U:%G %a' "$1")" = "$2:$3 $4" ]; then
    rm -f "$5"
    return 0
  fi
  chown "$2:$3" "$5"
  chmod "$4" "$5"
  mv -f "$5" "$1"
  say "Wrote $1."
}

ctl_text() {
  printf '#!/bin/sh\n# megoo-ctl %s, written by megoo-setup.sh: the only command MegooITAdmin may run with sudo.\n' "$CTL_VERSION"
  printf '# Do not edit it: run megoo-setup.sh again instead.\nCTL_VERSION=%s\n' "$CTL_VERSION"
  cat << 'CTL'
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
LC_ALL=C
export PATH LC_ALL

refuse() { echo "megoo-ctl: refused: $1" >&2; exit 2; }
container() {
  case "$1" in ''|[!A-Za-z0-9]*|*[!A-Za-z0-9_.-]*) refuse "not a container: $1" ;; esac
  [ ${#1} -le 128 ] || refuse "not a container: $1"
}
pid() {
  case "$1" in ''|*[!0-9]*|0*) refuse "not a process id: $1" ;; esac
  [ ${#1} -le 10 ] && [ "$1" -gt 1 ] || refuse "process $1 may not be touched"
}

verb=${1-}
[ $# -eq 0 ] || shift
case "$verb" in
  version)
    [ $# -eq 0 ] || refuse "version takes no arguments"
    echo "megoo-ctl $CTL_VERSION" ;;
  docker)
    sub=${1-}
    [ $# -eq 0 ] || shift
    case "$sub" in
      ps)
        [ $# -eq 0 ] || refuse "docker ps takes no arguments"
        exec docker ps --all --no-trunc --format '{{json .}}' ;;
      logs)
        [ $# -ge 1 ] || refuse "docker logs needs a container"
        name=$1
        shift
        container "$name"
        follow= tail= since=
        while [ $# -gt 0 ]; do
          case "$1" in
            --follow) follow=1; shift ;;
            --tail)
              [ $# -ge 2 ] || refuse "--tail needs a number"
              case "$2" in ''|*[!0-9]*) refuse "not a number: $2" ;; esac
              [ ${#2} -le 7 ] || refuse "not a number: $2"
              tail=$2; shift 2 ;;
            --since)
              [ $# -ge 2 ] || refuse "--since needs a time"
              case "$2" in ''|[!0-9]*|*[!0-9A-Za-z:.+-]*) refuse "not a time: $2" ;; esac
              [ ${#2} -le 40 ] || refuse "not a time: $2"
              since=$2; shift 2 ;;
            *) refuse "docker logs does not take $1" ;;
          esac
        done
        set -- --timestamps
        if [ -n "$follow" ]; then set -- "$@" --follow; fi
        if [ -n "$tail" ]; then set -- "$@" --tail "$tail"; fi
        if [ -n "$since" ]; then set -- "$@" --since "$since"; fi
        exec docker logs "$@" "$name" ;;
      start|stop|restart)
        [ $# -eq 1 ] || refuse "docker $sub takes one container"
        container "$1"
        exec docker "$sub" "$1" ;;
      *) refuse "docker ${sub:-without a command} is not allowed" ;;
    esac ;;
  kill)
    [ $# -ge 2 ] || refuse "kill needs a signal and a process id"
    case "$1" in TERM|KILL|HUP|STOP|CONT) ;; *) refuse "signal $1 is not allowed" ;; esac
    signal=$1
    shift
    for p in "$@"; do pid "$p"; done
    kill -s "$signal" "$@" ;;
  renice)
    [ $# -ge 2 ] || refuse "renice needs a priority and a process id"
    case "$1" in -[0-9]|-1[0-9]|-20|[0-9]|1[0-9]) ;; *) refuse "priority $1 is not allowed" ;; esac
    priority=$1
    shift
    for p in "$@"; do pid "$p"; done
    exec renice -n "$priority" -p "$@" ;;
  systemctl)
    [ $# -eq 2 ] || refuse "systemctl takes a verb and one unit"
    case "$1" in start|stop|restart|reload|enable|disable) ;; *) refuse "systemctl $1 is not allowed" ;; esac
    case "$2" in
      [!A-Za-z0-9]*|*[!A-Za-z0-9:_.@-]*) refuse "not a unit: $2" ;;
      *.service|*.socket|*.timer) ;;
      *) refuse "not a unit: $2" ;;
    esac
    exec systemctl --no-pager --no-ask-password "$1" -- "$2" ;;
  *) refuse "unknown call: ${verb:-none}" ;;
esac
CTL
}

if [ -z "$check" ]; then
  # 2. The account.
  if ! getent passwd "$user" > /dev/null; then
    useradd -m -s /bin/bash "$user"
    usermod -p '*' "$user"
    say "Created the account $user."
  fi
  # 3. Its groups.
  for group in systemd-journal adm; do
    if ! in_group "$user" "$group"; then usermod -aG "$group" "$user"; say "Added $user to $group."; fi
  done
  if getent group docker > /dev/null && in_group "$user" docker; then
    gpasswd -d "$user" docker > /dev/null
    say "Removed $user from the docker group: that group is as strong as root."
  fi
  # 4. megoo-ctl.
  [ -d /usr/local/sbin ] || install -d -m 0755 -o root -g root /usr/local/sbin
  tmp=$(mktemp /usr/local/sbin/.megoo-ctl.XXXXXX)
  ctl_text > "$tmp"
  write_file "$CTL" root root 755 "$tmp"
  # 5. The sudo rule. sudo skips files in /etc/sudoers.d whose name holds a dot, so the temporary file is never read.
  tmp=$(mktemp /etc/sudoers.d/.megoo-ctl.XXXXXX)
  printf '%s ALL=(root) NOPASSWD: %s\n' "$user" "$CTL" > "$tmp"
  chmod 440 "$tmp"
  if ! visudo -cf "$tmp" > /dev/null 2>&1; then
    rm -f "$tmp"
    echo "megoo-setup: the sudo rule did not pass visudo -c, so it was not installed." >&2
    exit 1
  fi
  write_file "/etc/sudoers.d/megoo-ctl-$user" root root 440 "$tmp"
  # 6. The key, accepted only from the platform's addresses.
  home=$(getent passwd "$user" | cut -d: -f6)
  group=$(id -gn "$user")
  [ -d "$home/.ssh" ] || install -d -m 0700 -o "$user" -g "$group" "$home/.ssh"
  chown "$user:$group" "$home/.ssh"
  chmod 0700 "$home/.ssh"
  # The temporary file is made only when the key file differs, so a run that changes nothing leaves .ssh untouched.
  authorized=$home/.ssh/authorized_keys
  if ! { [ -f "$authorized" ] && printf 'from="%s" %s\n' "$from" "$key" | cmp -s - "$authorized" \
    && [ "$(stat -c '%U:%G %a' "$authorized")" = "$user:$group 600" ]; }; then
    tmp=$(mktemp "$home/.ssh/.authorized_keys.XXXXXX")
    printf 'from="%s" %s\n' "$from" "$key" > "$tmp"
    write_file "$authorized" "$user" "$group" 600 "$tmp"
  fi
  [ -n "$changed" ] || echo "Nothing to change."
fi

# 7. The checks.
failed=0
ok() { printf '[ok]   %s\n' "$1"; }
fail() { printf '[FAIL] %s\n' "$1"; failed=$((failed + 1)); }
if ! getent passwd "$user" > /dev/null; then
  fail "The account $user does not exist."
  echo "$failed check(s) failed. Run megoo-setup.sh with --from and --key."
  exit 1
fi
ok "The account $user exists and is not root (uid $(id -u "$user"))."
if in_group "$user" docker; then fail "$user is in the docker group."; else ok "$user is not in the docker group."; fi
for group in systemd-journal adm; do
  if in_group "$user" "$group"; then ok "$user is in $group."; else fail "$user is not in $group."; fi
done
if [ -f "$CTL" ] && [ "$(stat -c '%U %a' "$CTL")" = "root 755" ] && [ "$("$CTL" version 2> /dev/null)" = "megoo-ctl $CTL_VERSION" ]; then
  ok "$CTL is version $CTL_VERSION, owned by root, mode 755."
else
  fail "$CTL is missing, out of date, or not owned by root with mode 755."
fi
allowed=$(sudo -l -U "$user" 2> /dev/null | sed -n '/may run the following commands/,$p' | sed '1d' \
  | sed -e 's/^[[:space:]]*//' -e '/^$/d' -e 's/^([^)]*)[[:space:]]*//' -e 's/^\([A-Z_]*:[[:space:]]*\)*//')
if [ "$allowed" = "$CTL" ]; then
  ok "sudo allows $user only $CTL."
else
  fail "sudo allows $user more than $CTL, or not $CTL. It allows:"
  printf '%s\n' "${allowed:-nothing}" | sed 's/^/         /'
fi
home=$(getent passwd "$user" | cut -d: -f6)
keys=$home/.ssh/authorized_keys
if [ -f "$keys" ] && [ "$(stat -c '%U %a' "$keys")" = "$user 600" ] && [ "$(stat -c '%U %a' "$home/.ssh")" = "$user 700" ] \
  && [ "$(grep -cv -e '^[[:space:]]*#' -e '^[[:space:]]*$' "$keys")" = 1 ] && grep -q '^from="[^"]*" ' "$keys"; then
  ok "$keys holds one key, $(ssh-keygen -l -f "$keys" | cut -d' ' -f2), accepted from $(sed -n 's/^from="\([^"]*\)" .*/\1/p' "$keys")."
else
  fail "$keys must hold exactly one key limited with from=\"…\", owned by $user, mode 600, in a 700 directory."
fi
if [ "$failed" = 0 ]; then
  echo "The server is ready. Pin its host key and test the connection on the server page."
  echo "Also limit SSH (port 22) to the platform's address in the firewall or security group: see docs/server-setup.md."
  exit 0
fi
echo "$failed check(s) failed."
exit 1
