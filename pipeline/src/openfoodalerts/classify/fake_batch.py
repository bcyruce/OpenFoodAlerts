"""A local stand-in Batch API for the fake model: `ofa classify --batch --model fake` runs the
whole submit -> status -> results -> store cycle without a provider or a key (demos, the
CLI tests). A submitted batch is a JSONL file in OFA_FAKE_BATCH_DIR (default: a folder in
the system temp directory); it has ended as soon as it exists, and its results are the
fake model's answers, computed when they are read. Not a real model (classify.fake).
"""

import json
import os
import tempfile
import uuid
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

from openfoodalerts.classify.batch import BatchRequest, BatchResult, BatchStatus
from openfoodalerts.classify.fake import FAKE_MODEL, KeywordClassifier
from openfoodalerts.classify.model import ModelRequest
from openfoodalerts.eval.labelset import Taxonomy


def default_dir() -> Path:
    configured = os.environ.get("OFA_FAKE_BATCH_DIR")
    return Path(configured) if configured else Path(tempfile.gettempdir()) / "ofa-fake-batches"


class FakeBatches:
    provider = "fake"
    model = FAKE_MODEL

    def __init__(self, taxonomy: Taxonomy, directory: Path | None = None) -> None:
        self.classifier = KeywordClassifier(taxonomy)
        self.directory = directory or default_dir()

    def params(self, request: ModelRequest) -> dict[str, Any]:
        # the fake model reads the snapshot, not the rendered message
        return {
            "task": request.task,
            "source": request.source,
            "snapshot": dict(request.snapshot),
            "system": request.system,
            "user": request.user,
            "output_schema": request.output_schema,
        }

    def _path(self, batch_id: str) -> Path:
        return self.directory / f"{batch_id}.jsonl"

    def submit(self, requests: Sequence[BatchRequest]) -> str:
        self.directory.mkdir(parents=True, exist_ok=True)
        batch_id = f"fakebatch_{uuid.uuid4().hex[:12]}"
        lines = (json.dumps({"custom_id": r.custom_id, "params": r.params}) for r in requests)
        self._path(batch_id).write_text("\n".join(lines) + "\n", encoding="utf-8")
        return batch_id

    def status(self, batch_id: str) -> BatchStatus:
        if not self._path(batch_id).exists():
            return BatchStatus(True, f"gone: {self._path(batch_id)} does not exist")
        return BatchStatus(True, "ended")

    def results(self, batch_id: str) -> Iterator[BatchResult]:
        path = self._path(batch_id)
        if not path.exists():
            return
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                request = json.loads(line)
                answer = self.classifier.complete(ModelRequest(**request["params"]))
                yield BatchResult(request["custom_id"], answer)
