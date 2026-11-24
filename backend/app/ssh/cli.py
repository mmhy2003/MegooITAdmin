"""Host commands, run in the backend container: python -m app.ssh.cli ensure-key | public-key."""

import argparse
import sys

from app.ssh import keys


def ensure_key() -> int:
    if keys.ensure_key():
        print(
            f"Created the platform's SSH key in {keys.key_path()}. Put its public key on every server: "
            "make ssh-public-key"
        )
    else:
        print(f"The platform's SSH key is in {keys.key_path()}.")
    return 0


def public_key() -> int:
    print(keys.public_key())
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.ssh.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("ensure-key", help="Make the platform's SSH key if there is none, and check its mode")
    commands.add_parser("public-key", help="Print the platform's SSH public key, for authorized_keys")
    args = parser.parse_args(argv)
    try:
        return ensure_key() if args.command == "ensure-key" else public_key()
    except keys.KeyFileError as error:
        print(error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
