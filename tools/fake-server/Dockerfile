# The fake server of the tests and the dev stacks: real OpenSSH, key sign-in only. It is never a real server.
FROM debian:trixie-slim
RUN apt-get update && apt-get install -y --no-install-recommends openssh-server sudo procps openssl && rm -rf /var/lib/apt/lists/*
# megoo, the account the platform uses, and the broken megoo-nologs, megoo-nosudo and megoo-wide are made by
# authorize-key through megoo-setup.sh. megoo-docker (in docker) and megoo-root (uid 0) are made here, as the script
# would refuse them, so the account check can be tested. '*' is no password, but not a locked account, so key sign-in
# works. megoo-setup.sh needs systemd-journal: made here unless a package of the install above already made it.
RUN groupadd docker \
 && { getent group systemd-journal > /dev/null || groupadd -r systemd-journal; } \
 && useradd -m -s /bin/bash -G docker megoo-docker \
 && useradd -o -u 0 -g 0 -M -d /home/megoo-root -s /bin/bash megoo-root \
 && install -d -m 0755 /home/megoo-root \
 && usermod -p '*' megoo-docker && usermod -p '*' megoo-root
COPY sshd_config /etc/ssh/sshd_config.d/fake-server.conf
COPY entrypoint.sh authorize-key swap-host-key /usr/local/bin/
RUN chmod 0755 /usr/local/bin/entrypoint.sh /usr/local/bin/authorize-key /usr/local/bin/swap-host-key
EXPOSE 22
# megoo-setup.sh comes from the setup build context (backend/app/ssh). fake-tool stands in for docker, systemctl,
# journalctl, apt-get and dnf: it logs each call to /var/log/fake-tools.log and prints its fixture from
# /etc/fake-tools. megoo calls the stubs without sudo too, so every account may write the log. The real journalctl
# and systemctl (Debian's systemd, pulled in above) are removed, so a test that hides a stub hides the tool.
COPY --from=setup megoo-setup.sh /usr/local/lib/megoo-setup.sh
COPY fake-tool /usr/local/bin/docker
COPY fake-tool /usr/local/bin/systemctl
COPY fake-tool /usr/local/bin/journalctl
COPY fake-tool /usr/local/bin/apt-get
COPY fake-tool /usr/local/bin/dnf
COPY fixtures/ /etc/fake-tools/
RUN rm -f /usr/bin/journalctl /usr/bin/systemctl \
 && chmod 0755 /usr/local/bin/docker /usr/local/bin/systemctl /usr/local/bin/journalctl /usr/local/bin/apt-get \
      /usr/local/bin/dnf \
 && touch /var/log/fake-tools.log && chmod 0666 /var/log/fake-tools.log
ENTRYPOINT ["entrypoint.sh"]
