# Preparing a server for MegooITAdmin

MegooITAdmin signs in to a Linux server as one account, `megoo` by default, never as root. One script,
`megoo-setup.sh`, prepares that account on each server. Test connection on the server page then checks seven
things: the host key, the platform's key, not root, not in `docker`, in the log groups, `megoo-ctl` answers through
sudo, and sudo allows nothing else.

## What the script does

Get it from the server page (Platform access → Download megoo-setup.sh) or from the repository
(`backend/app/ssh/megoo-setup.sh`). Both are the same file. Copy it to the server and run it as root:

```sh
sudo sh megoo-setup.sh --from <addresses> --key '<key>' [--user <name>]
sudo sh megoo-setup.sh --check [--user <name>]
```

- `--from` is the address the server sees the platform under. The platform cannot know it (NAT, several
  interfaces), so you type it. Several addresses or ranges are separated by commas, as in `authorized_keys`.
- `--key` is the platform's public key line. The Platform access card shows the whole command with the key filled
  in, and `make ssh-public-key` prints the key.
- `--user` names another login account. It is never `root`, nor an account with uid 0.

A run takes these steps. Each is safe to repeat: a second run changes nothing and prints the same checks.

1. It checks the arguments, root, and the tools and groups it needs before it changes anything.
2. It creates the account when it is missing: a home directory, `/bin/bash`, and no password.
3. It adds the account to `systemd-journal` and `adm`, to read the logs. It removes the account from `docker`, which
   is as strong as root, and says so.
4. It writes `/usr/local/sbin/megoo-ctl` (root, mode 755): the only command the account may run with sudo.
5. It writes `/etc/sudoers.d/megoo-ctl-<user>` (root, mode 440) with `<user> ALL=(root) NOPASSWD:
   /usr/local/sbin/megoo-ctl`. The rule is checked with `visudo -c` first, and a rule that fails is never installed.
6. It writes the account's `~/.ssh/authorized_keys` (mode 600, directory 700) with one line,
   `from="<addresses>" <key>`. The file holds only the platform's key: other keys in it are replaced. The account owns
   `~/.ssh`, so the script writes there as the account (`runuser`), and refuses to run when `~/.ssh` or
   `authorized_keys` is a symbolic link: otherwise the account could have root change another file.
7. It checks all of the above and prints one line per check.

`--check` runs only step 7 and changes nothing.

The exit code is 0 when the server is ready (`The server is ready.`), 1 when a check failed, and 2 when the script
refused before changing anything (not root, a tool missing, a wrong argument, a symbolic link in `~/.ssh`).

Supported: Linux with systemd, sudo and OpenSSH, such as Debian, Ubuntu and the RHEL family.

The script never:

- installs a package. It stops and says what is missing when `sudo`, `visudo`, `useradd` or the `systemd-journal`
  group is not there;
- changes sshd or the firewall (see below to limit port 22);
- removes other sudo rights of the account, such as the `sudo` or `wheel` group or another file in
  `/etc/sudoers.d`. It reports them as a failed check: remove them yourself and run `--check` again.

## What megoo-ctl allows

`megoo-ctl` version 1 chooses the options of every command itself. A caller chooses a call and a target, never free
options. Anything else is refused with exit 2 before any tool runs. MegooITAdmin calls it as
`sudo -n /usr/local/sbin/megoo-ctl <call>`.

| Call | Runs | Accepts |
|---|---|---|
| `version` | prints `megoo-ctl 1` | nothing else |
| `docker ps` | `docker ps --all --no-trunc --format '{{json .}}'` | nothing else |
| `docker logs <container> [--follow] [--tail <n>] [--since <time>]` | `docker logs --timestamps …` | a number for `--tail`, a timestamp or a duration for `--since` |
| `docker start\|stop\|restart <container>` | the same | one container |
| `kill <TERM\|KILL\|HUP\|STOP\|CONT> <pid>…` | `kill -s <signal> <pid>…` | numeric PIDs above 1 |
| `renice <priority> <pid>…` | `renice -n <priority> -p <pid>…` | -20 to 19, numeric PIDs above 1 |
| `systemctl start\|stop\|restart\|reload\|enable\|disable <unit>` | `systemctl --no-pager --no-ask-password <verb> -- <unit>` | one unit of letters, digits and `:_.@-`, ending in `.service`, `.socket` or `.timer` |

A container is a name or an id: it starts with a letter or a digit and holds only letters, digits and `_.-`.

## Limit SSH to the platform's address

The script accepts the platform's key only from `--from`, but other accounts can still sign in from anywhere.
Close port 22 to every other address in the firewall too.

Before you close it, keep a way back in: a console from your provider, or another address you allow as well.

With ufw (Debian, Ubuntu):

```sh
sudo ufw allow from <addr> to any port 22 proto tcp
sudo ufw deny 22/tcp
```

Remove any earlier rule that allows SSH from everywhere (`sudo ufw status numbered`, then `sudo ufw delete <n>`).

With firewalld (the RHEL family):

```sh
sudo firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="<addr>" port port="22" protocol="tcp" accept'
sudo firewall-cmd --permanent --remove-service=ssh
sudo firewall-cmd --reload
```

In a cloud security group: one inbound rule for TCP 22 from `<addr>/32`, and no other rule for port 22.

## Remote Desktop (Windows, Phase 2)

Windows servers connect from Phase 2. To limit Remote Desktop to the platform's address, run this in an elevated
PowerShell:

```powershell
Set-NetFirewallRule -DisplayGroup "Remote Desktop" -RemoteAddress <addr>
```

## Run it again

Run the script again, with the same `--from` and `--key`:

- after a MegooITAdmin upgrade that raises `megoo-ctl`'s version. Test connection then says
  `megoo-ctl is missing or out of date.`;
- after the platform gets a new key. The script replaces the old key in `authorized_keys`.

## Remove the setup

```sh
sudo rm /etc/sudoers.d/megoo-ctl-megoo /usr/local/sbin/megoo-ctl
sudo userdel -r megoo
```

For another account, use its name in the sudoers file and in `userdel`.

## Checklist for a real server

The Owner prepares one real test server by hand (agents never connect to a managed server):

1. Download `megoo-setup.sh` from the Platform access card and copy it to the server.
2. Run the command from the card with the platform's address as `--from`, and see `The server is ready.`
3. Register the server, then pin its host key after comparing the fingerprint
   (`ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`).
4. Press Test connection: seven checks pass.
5. Run `sudo sh megoo-setup.sh --check` on the server once more: it still says `The server is ready.`
