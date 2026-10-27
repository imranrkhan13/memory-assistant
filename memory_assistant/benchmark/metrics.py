"""Standard-library port of LongMemEval eval_utils.py session metrics.

Upstream revision 9e0b455f4ef0e2ab8f2e582289761153549043fc (MIT).
See benchmarks/longmemeval/upstream for the unmodified sources and licence.
The upstream discount is 1, 1/log2(2), 1/log2(3), ... (not rank+1).
"""
import math

METRIC_VERSION = 'longmemeval-session-9e0b455f-stdlib-v1'


def dcg(relevances, k):
    values = list(relevances)[:k]
    if not values:
        return 0.0
    return values[0] + sum(value / math.log2(rank) for rank, value in enumerate(values[1:], 2))


def session_metrics(ranked_ids, correct_ids, corpus_ids, k=10):
    """Unique session ranking; missing evidence cannot silently improve the ideal."""
    if k < 1:
        raise ValueError('k must be positive.')
    if len(ranked_ids) != len(set(ranked_ids)) or len(corpus_ids) != len(set(corpus_ids)):
        raise ValueError('Session rankings and corpus must not contain duplicates.')
    if not correct_ids or not set(correct_ids).issubset(corpus_ids):
        raise ValueError('Scored questions require evidence sessions in the corpus.')
    if not set(ranked_ids).issubset(corpus_ids):
        raise ValueError('Ranked session outside corpus.')
    selected = ranked_ids[:k]
    relevant = set(correct_ids)
    ideal = dcg(sorted([int(value in relevant) for value in corpus_ids], reverse=True), k)
    actual = dcg([int(value in relevant) for value in selected], k)
    return {
        f'recall_all@{k}': float(relevant.issubset(selected)),
        f'ndcg_any@{k}': actual / ideal if ideal else 0.0,
    }
