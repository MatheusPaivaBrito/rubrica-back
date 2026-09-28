"""Explicit one-shot migrations; stop on the first failed database."""
import argparse
import subprocess
import sys

DATABASES = ("auth", "core", "eventing", "notification")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", choices=("all", *DATABASES), default="all", nargs="?")
    args = parser.parse_args()
    for database in DATABASES if args.database == "all" else (args.database,):
        subprocess.run(
            [sys.executable, "-m", "alembic", "-c", f"apps/{database}_api/alembic.ini", "upgrade", "head"],
            check=True,
        )


if __name__ == "__main__":
    main()
