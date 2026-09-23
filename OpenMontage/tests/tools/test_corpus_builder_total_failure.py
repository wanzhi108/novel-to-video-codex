from dataclasses import dataclass

import pytest

import tools.video.stock_sources as stock_sources
from tools.video.corpus_builder import CorpusBuilder


@dataclass
class _Candidate:
    clip_id: str


class _Source:
    name = "fake"

    def __init__(self, count: int) -> None:
        self.count = count

    def is_available(self) -> bool:
        return True

    def search(self, query, filters):
        return [_Candidate(f"clip-{index}") for index in range(self.count)]


@pytest.fixture
def run_builder(monkeypatch, tmp_path):
    def run(count: int, processor):
        monkeypatch.setattr(stock_sources, "available_sources", lambda: [_Source(count)])
        monkeypatch.setattr(stock_sources, "source_summary", lambda: {})
        monkeypatch.setattr(CorpusBuilder, "_process_candidate", processor)
        return CorpusBuilder().execute({
            "corpus_dir": str(tmp_path / f"corpus-{count}"),
            "queries": [{"query": "city at night"}],
            "max_new_clips": 50,
        })

    return run


def test_all_candidate_failures_fail_closed_with_diagnostics(run_builder) -> None:
    def broken_clip_stack(*args, **kwargs):
        raise AttributeError("BaseModelOutput has no attribute norm")

    result = run_builder(4, broken_clip_stack)

    assert result.success is False
    assert result.data["candidates_seen"] == 4
    assert result.data["clips_failed"] == 4
    assert "corpus index is empty" in result.error
    assert "BaseModelOutput" in result.error


def test_no_candidates_is_a_valid_empty_search(run_builder) -> None:
    result = run_builder(0, lambda *args, **kwargs: None)

    assert result.success is True
    assert result.data["candidates_seen"] == 0
