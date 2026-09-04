"""Load seed fixtures into a database."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from app.env import load_env
from app.infrastructure.db import open_database
from app.seed.fixtures import load_reference_data


def main() -> None:
    load_env()
    parser = argparse.ArgumentParser(description="Load reference seed data.")
    parser.add_argument(
        "--database",
        default=os.environ.get("CLAIMS_DATABASE", "claims.db"),
        help="SQLite database file path",
    )
    args = parser.parse_args()
    path = Path(args.database)
    db = open_database(str(path))
    try:
        load_reference_data(db)
        db.connection.commit()
        print(f"Loaded reference data into {path}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
