# The fake server of the tests and the dev stacks: real OpenSSH, key sign-in only. It is never a real server.
FROM debian:trixie-slim
RUN apt-get update && apt-get install -y --no-install-recommends openssh-server sudo procps && rm -rf /var/lib/apt/lists/*
# megoo is the account the platform uses. megoo-docker (in docker) and megoo-root (uid 0) exist so the account
# check can be tested. '*' is no password, but not a locked account, so key sign-in works.
# megoo-setup.sh needs systemd-journal: made here unless a package of the install above already made it.
RUN groupadd docker \
 && { getent group systemd-journal > /dev/null || groupadd -r systemd-journal; } \
 && useradd -m -s /bin/bash megoo \
 && useradd -m -s /bin/bash -G docker megoo-docker \
 && useradd -o -u 0 -g 0 -M -d /home/megoo-root -s /bin/bash megoo-root \
 && install -d -m 0755 /home/megoo-root \
 && usermod -p '*' megoo && usermod -p '*' megoo-docker && usermod -p '*' megoo-root
COPY sshd_config /etc/ssh/sshd_config.d/fake-server.conf
COPY entrypoint.sh authorize-key swap-host-key /usr/local/bin/
RUN chmod 0755 /usr/local/bin/entrypoint.sh /usr/local/bin/authorize-key /usr/local/bin/swap-host-key
EXPOSE 22
# megoo-setup.sh comes from the setup build context (backend/app/ssh). fake-tool stands in for docker and systemctl
# and logs what megoo-ctl passes on to /var/log/fake-tools.log.
COPY --from=setup megoo-setup.sh /usr/local/lib/megoo-setup.sh
COPY fake-tool /usr/local/bin/docker
COPY fake-tool /usr/local/bin/systemctl
RUN chmod 0755 /usr/local/bin/docker /usr/local/bin/systemctl && touch /var/log/fake-tools.log
ENTRYPOINT ["entrypoint.sh"]
