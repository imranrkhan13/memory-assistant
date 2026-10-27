"""Deterministic splits fixed from IDs/types/abstention markers before retrieval."""
from collections import Counter, defaultdict
import hashlib


def quotas(groups, total):
    """Largest-remainder proportional allocation, with stable tie breaking."""
    available = sum(len(values) for values in groups.values())
    if total > available or total < 0:
        raise ValueError('Not enough questions for the requested split.')
    allocated = {key: len(values) * total // available for key, values in groups.items()}
    order = sorted(groups, key=lambda key: (-(len(groups[key]) * total % available), key))
    for key in order[:total - sum(allocated.values())]:
        allocated[key] += 1
    return allocated


def build_splits(metadata, seed, dev_size=40, heldout_size=60):
    """Only question_id/question_type/abstention are accepted as selection inputs."""
    groups = defaultdict(list)
    seen = set()
    for item in metadata:
        question_id, question_type, abstention = item
        if question_id in seen:
            raise ValueError('Duplicate question ID.')
        seen.add(question_id)
        groups[(question_type, abstention)].append(question_id)
    for values in groups.values():
        values.sort(key=lambda question_id: hashlib.sha256(f'{seed}:{question_id}'.encode()).hexdigest())
    output = {}
    for name, size in [('dev', dev_size), ('heldout', heldout_size)]:
        allocation = quotas(groups, size)
        selected = []
        counts = Counter()
        abstentions = 0
        for key in sorted(groups):
            amount = allocation[key]
            selected.extend(groups[key][:amount])
            counts[key[0]] += amount
            if key[1]:
                abstentions += amount
            groups[key] = groups[key][amount:]
        output[name] = sorted(selected)
        output[f'{name}_counts_by_type'] = dict(sorted(counts.items()))
        output[f'{name}_abstentions'] = abstentions
    return output
