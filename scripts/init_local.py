"""Generate local credentials once; never print or silently rotate them."""

import argparse
import os
import re
import secrets
from pathlib import Path


def initialize(root: Path) -> None:
    directory = root / ".secrets"
    names = ("postgres_password", "redis_password")
    present = [directory / name for name in names if (directory / name).exists()]
    if present:
        if len(present) != len(names):
            raise ValueError(
                "Incomplete .secrets directory; restore missing credentials, do not rotate automatically"
            )
        for path in present:
            value = path.read_text(encoding="utf-8").strip()
            if not re.fullmatch(r"[0-9a-f]{64}", value) or len(set(value)) < 8:
                raise ValueError("Invalid local secret; restore credentials before startup")
        if os.name != "nt":
            directory.chmod(0o700)
            for path in present:
                path.chmod(0o444)
        print("Local credentials already initialized; preserved.")
        return
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    for name in names:
        path = directory / name
        with path.open("x", encoding="utf-8", newline="\n") as file:
            file.write(secrets.token_hex(32) + "\n")
        if os.name != "nt":
            # Compose file secrets are bind mounts: non-root container UIDs must be able to read
            # the file. The host directory remains 0700, preventing other host users traversing it.
            path.chmod(0o444)
    print("Initialized .secrets (values hidden). Keep this directory private and backed up.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    try:
        initialize(Path(__file__).resolve().parents[1])
    except ValueError as error:
        parser.exit(1, str(error) + "\n")
