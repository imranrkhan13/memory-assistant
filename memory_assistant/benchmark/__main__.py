"""Run offline keyword evidence evaluation; never load .env or model providers."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys
import urllib.error

from .dataset import BENCHMARK_DIR, DATASET_PATH, download_dataset
from .runner import run_keyword, write_report


def main(argv=None):
    parser = argparse.ArgumentParser(description='Model-free LongMemEval retrieval benchmark')
    commands = parser.add_subparsers(dest='command', required=True)
    download = commands.add_parser('download', help='Download and verify the pinned public cleaned S file')
    download.add_argument('--dataset', type=Path, default=DATASET_PATH)
    run = commands.add_parser('run', help='Run retrieval on the frozen dev subset only')
    run.add_argument('--method', choices=['keyword'], required=True)
    run.add_argument('--subset', choices=['dev'], required=True)
    run.add_argument('--dataset', type=Path, default=DATASET_PATH)
    run.add_argument('--index', type=Path, default=BENCHMARK_DIR / 'local' / 'keyword.sqlite3')
    run.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == 'download':
            path = download_dataset(args.dataset)
            print('Pinned dataset verified:', path)
            return 0
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        output = args.output or BENCHMARK_DIR / 'results' / f'keyword-dev-{stamp}.json'
        if output.exists():
            raise ValueError('Output exists; choose a new path to preserve the earlier run.')
        report = run_keyword(dataset_path=args.dataset, index_path=args.index, subset=args.subset)
        write_report(report, output)
        summary = report['summary']
        print('Provider: none (retrieval only); model calls: 0')
        print(f"Selected: {summary['selected']}; eligible: {summary['eligible']}; scored: {summary['scored']}; failed: {summary['failed']}; skipped abstentions: {summary['skipped_abstentions']}")
        for metric, value in summary['metrics'].items():
            print(f'{metric}: {value:.6f}' if value is not None else f'{metric}: not scored')
        print('Retrieval latency (ms):', summary['retrieval_ms'])
        print('Questions with missed evidence:')
        for row in summary['misses']:
            print(f"  {row['question_id']}: {', '.join(row['missing_session_ids'])}")
        if summary['failures']:
            print('Failed questions:', summary['failures'])
        print('Results:', output)
        return 1 if summary['failed'] else 0
    except (ValueError, OSError, urllib.error.URLError) as error:
        print(f'Benchmark error: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
