import pytest

from benchmarks.stats import format_summary, percentile, summarize


def test_nearest_rank_percentile():
    samples = list(range(1, 101))
    assert percentile(samples, 50) == 50
    assert percentile(samples, 95) == 95
    assert percentile(samples, 100) == 100
    assert percentile([7.0], 95) == 7.0
    assert percentile([3, 1, 2], 0) == 1


def test_percentile_validation():
    with pytest.raises(ValueError):
        percentile([], 50)
    with pytest.raises(ValueError):
        percentile([1], 101)


def test_summary():
    s = summarize([1.0, 2.0, 3.0, 4.0])
    assert (s["min"], s["avg"], s["max"]) == (1.0, 2.5, 4.0)
    assert format_summary("US", [1.0, 2.0]).startswith("US ")
