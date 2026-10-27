"""Pinned LongMemEval input, with separate ingestion and scoring records."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
BENCHMARK_DIR = ROOT / 'benchmarks' / 'longmemeval'
MANIFEST_PATH = BENCHMARK_DIR / 'manifest.json'
DATASET_PATH = BENCHMARK_DIR / 'local' / 'longmemeval_s_cleaned.json'
QUESTION_TYPES = (
    'single-session-user', 'single-session-assistant',
    'single-session-preference', 'temporal-reasoning',
    'knowledge-update', 'multi-session',
)


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def read_manifest(path=MANIFEST_PATH):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def verify_dataset(path, manifest):
    path = Path(path)
    if not path.is_file():
        raise ValueError('Dataset missing. Run: python3 -m memory_assistant.benchmark download')
    expected = manifest['dataset']
    if path.stat().st_size != expected['size_bytes'] or sha256_file(path) != expected['sha256']:
        raise ValueError('Dataset size/SHA-256 mismatch; expected the pinned cleaned S release.')


def download_dataset(path=DATASET_PATH, manifest_path=MANIFEST_PATH):
    """Fetch only the pinned public file; require exact bytes before publishing it."""
    manifest = read_manifest(manifest_path)
    path = Path(path)
    if path.exists():
        verify_dataset(path, manifest)
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.download')
    dataset = manifest['dataset']
    try:
        # Exclusive creation prevents concurrent downloaders from sharing a file.
        with temporary.open('xb') as target:
            with urllib.request.urlopen(dataset['url'], timeout=60) as response:
                size = 0
                for block in iter(lambda: response.read(1024 * 1024), b''):
                    size += len(block)
                    if size > dataset['size_bytes']:
                        raise ValueError('Dataset exceeded pinned size.')
                    target.write(block)
        verify_dataset(temporary, manifest)
        temporary.replace(path)
    except FileExistsError:
        raise ValueError('A download is already present/in progress; inspect the .download file.') from None
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return path


def iter_records(path, block_size=1024 * 1024):
    """Stream a JSON array one question at a time, using only the stdlib.

    This avoids loading all 277 MB (and its decoded objects) into memory.
    It validates separators and trailing input, including truncated downloads.
    """
    decoder = json.JSONDecoder()
    with Path(path).open(encoding='utf-8') as source:
        buffer = ''
        eof = False

        def more():
            nonlocal buffer, eof
            chunk = source.read(block_size)
            if not chunk:
                eof = True
            buffer += chunk

        def space():
            nonlocal buffer
            while True:
                buffer = buffer.lstrip()
                if buffer or eof:
                    return
                more()

        more()
        space()
        if not buffer.startswith('['):
            raise ValueError('Dataset must be a JSON array.')
        buffer = buffer[1:]
        first = True
        while True:
            space()
            if buffer.startswith(']'):
                buffer = buffer[1:]
                if not first:
                    # A closing bracket after a comma is invalid JSON.
                    raise ValueError('Trailing comma in dataset.')
                break
            if not first:
                if not buffer.startswith(','):
                    raise ValueError('Missing dataset record separator.')
                buffer = buffer[1:]
                space()
            while True:
                try:
                    record, end = decoder.raw_decode(buffer)
                    break
                except json.JSONDecodeError as error:
                    if eof:
                        raise ValueError('Malformed or truncated dataset.') from error
                    more()
            if not isinstance(record, dict):
                raise ValueError('Every dataset question must be an object.')
            yield record
            buffer = buffer[end:]
            space()
            if buffer.startswith(']'):
                buffer = buffer[1:]
                break
            first = False
        # Read to EOF, rejecting non-whitespace after the top-level array.
        while not eof:
            more()
        if buffer.strip():
            raise ValueError('Unexpected data after dataset array.')


@dataclass(frozen=True)
class Turn:
    role: str
    content: str


@dataclass(frozen=True)
class Session:
    session_id: str
    timestamp: str
    turns: tuple[Turn, ...]


@dataclass(frozen=True)
class History:
    question_id: str
    sessions: tuple[Session, ...]


@dataclass(frozen=True)
class EvaluationQuery:
    question_id: str
    question_type: str
    question: str
    evidence_session_ids: tuple[str, ...]
    abstention: bool


def history_from_record(record):
    """Allowlist only history fields. Query, reference and labels never cross here."""
    question_id = record['question_id']
    ids = record['haystack_session_ids']
    dates = record['haystack_dates']
    sessions = record['haystack_sessions']
    if not isinstance(question_id, str) or not question_id:
        raise ValueError('Invalid question namespace.')
    if not all(isinstance(items, list) for items in (ids, dates, sessions)):
        raise ValueError('History fields must be arrays.')
    if len(ids) != len(dates) or len(ids) != len(sessions):
        raise ValueError('Session IDs, timestamps and sessions must align.')
    if any(not isinstance(value, str) or not value for value in ids):
        raise ValueError('Session IDs must be nonempty strings.')
    result = []
    for session_id, timestamp, turns in zip(ids, dates, sessions):
        if not isinstance(timestamp, str) or not isinstance(turns, list):
            raise ValueError('Invalid session timestamp or turns.')
        cleaned = []
        for turn in turns:
            if not isinstance(turn, dict) or turn.get('role') not in ('user', 'assistant', 'system') or not isinstance(turn.get('content'), str):
                raise ValueError('Invalid history turn.')
            cleaned.append(Turn(role=turn['role'], content=turn['content']))
        result.append(Session(session_id, timestamp, tuple(cleaned)))
    return History(question_id, tuple(result))


def query_from_record(record):
    """Scoring metadata is separate from the index; reference answers are unused."""
    question_id = record['question_id']
    kind = record['question_type']
    question = record['question']
    evidence = record['answer_session_ids']
    if kind not in QUESTION_TYPES or not isinstance(question, str) or not question.strip():
        raise ValueError('Invalid evaluation query/type.')
    if not isinstance(evidence, list) or any(not isinstance(value, str) for value in evidence):
        raise ValueError('Invalid scoring session IDs.')
    if len(set(evidence)) != len(evidence) or not set(evidence).issubset(record['haystack_session_ids']):
        raise ValueError('Evidence IDs must identify unique history sessions.')
    abstention = '_abs' in question_id  # Match the official reporting filter.
    if not abstention and not evidence:
        raise ValueError('Non-abstention question has no evidence sessions.')
    return EvaluationQuery(question_id, kind, question, tuple(evidence), abstention)
