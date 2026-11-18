"""Seed through the same versioned ingestion path; never bypass SQL metadata."""

import tempfile
import uuid
from pathlib import Path

from worker.config import WorkerConfig
from worker.index_document import index_file


def main():
    if WorkerConfig().qdrant_collection != "fpi_demo":
        raise RuntimeError("Demo indexing permitted only for fpi_demo collection")
    with tempfile.TemporaryDirectory(prefix="rag-demo-") as directory:
        path = Path(directory) / "faculty-certificates-demo.txt"
        path.write_text(
            "Учебные справки выдаются в деканате по будням с 10:00 до 15:00.", encoding="utf-8"
        )
        index_file(path, uuid.uuid5(uuid.NAMESPACE_URL, "fpi-rag-demo:spravki"))


if __name__ == "__main__":
    main()
