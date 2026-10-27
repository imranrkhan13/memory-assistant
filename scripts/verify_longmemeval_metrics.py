"""Optional one-time audit against upstream NumPy code, not an app dependency.

Run with an already available NumPy installation. Normal app/tests use stdlib.
"""
import importlib.util
from pathlib import Path
import random
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from memory_assistant.benchmark.dataset import BENCHMARK_DIR, read_manifest, sha256_file
from memory_assistant.benchmark.metrics import session_metrics


def main():
    import numpy as np
    source = BENCHMARK_DIR / 'upstream' / 'eval_utils.py'
    expected = read_manifest()['official_metrics']['files']['src/retrieval/eval_utils.py']
    if sha256_file(source) != expected:
        raise ValueError('Pinned official source hash mismatch.')
    # NumPy 2 removed this old API; restore its float-array equivalent for audit.
    if not hasattr(np, 'asfarray'):
        np.asfarray = lambda values: np.asarray(values, dtype=float)
    spec = importlib.util.spec_from_file_location('official_longmemeval', source)
    official = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(official)
    rng = random.Random(27102026)
    maximum_error = 0.0
    comparisons = 0
    for _ in range(1000):
        corpus = [f'session_{number}' for number in range(rng.randint(1, 60))]
        correct = rng.sample(corpus, rng.randint(1, len(corpus)))
        ranked = rng.sample(corpus, rng.randint(0, len(corpus)))
        rankings = [corpus.index(value) for value in ranked]
        for k in (5, 10):
            _, expected_recall, expected_ndcg = official.evaluate_retrieval(rankings, correct, corpus, k)
            actual = session_metrics(ranked, correct, corpus, k)
            assert actual[f'recall_all@{k}'] == expected_recall
            error = abs(actual[f'ndcg_any@{k}'] - expected_ndcg)
            assert error < 1e-12, (actual, expected_ndcg)
            maximum_error = max(maximum_error, error)
            comparisons += 1
    print(f'Official-source conformance: {comparisons} comparisons, 0 failures; maximum absolute nDCG error={maximum_error:.3g}; NumPy={np.__version__}')


if __name__ == '__main__':
    main()
