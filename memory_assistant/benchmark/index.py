"""A rebuildable SQLite index of benchmark turns, never product memory."""
import json
from pathlib import Path
import sqlite3
import time

from .dataset import History
from ..retrieval import tokens

INDEX_VERSION = 'raw-turn-keyword-v1'


class BenchmarkIndex:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute('PRAGMA foreign_keys=ON')
        tables = {row[0] for row in self.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if tables and not tables.issubset({'benchmark_sessions', 'benchmark_chunks'}):
            self.connection.close()
            raise ValueError('Refusing a database that is not a dedicated benchmark index.')
        self.connection.executescript('''
            CREATE TABLE IF NOT EXISTS benchmark_sessions (
                question_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                session_ordinal INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                PRIMARY KEY(question_id, session_ordinal)
            );
            CREATE TABLE IF NOT EXISTS benchmark_chunks (
                question_id TEXT NOT NULL,
                chunk_id INTEGER NOT NULL,
                session_id TEXT NOT NULL,
                session_ordinal INTEGER NOT NULL,
                turn_ordinal INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                tokens_json TEXT NOT NULL,
                PRIMARY KEY(question_id, chunk_id),
                FOREIGN KEY(question_id, session_ordinal)
                    REFERENCES benchmark_sessions(question_id, session_ordinal)
                    ON DELETE CASCADE
            );
        ''')

    def close(self):
        self.connection.close()

    def ingest(self, history):
        """Accept only the history projection; no scoring/query object is allowed."""
        if not isinstance(history, History):
            raise TypeError('Ingestion requires a History projection, not a dataset record.')
        with self.connection:
            self.connection.execute('DELETE FROM benchmark_sessions WHERE question_id=?', (history.question_id,))
            chunk_id = 0
            for ordinal, session in enumerate(history.sessions):
                self.connection.execute('INSERT INTO benchmark_sessions VALUES(?,?,?,?)', (history.question_id, session.session_id, ordinal, session.timestamp))
                for turn_ordinal, turn in enumerate(session.turns):
                    chunk_id += 1
                    self.connection.execute('INSERT INTO benchmark_chunks VALUES(?,?,?,?,?,?,?,?)', (
                        history.question_id, chunk_id, session.session_id, ordinal, turn_ordinal,
                        turn.role, turn.content, json.dumps(sorted(tokens(turn.content))),
                    ))
        return chunk_id

    def corpus_session_ids(self, question_id):
        return list(dict.fromkeys(row[0] for row in self.connection.execute('SELECT session_id FROM benchmark_sessions WHERE question_id=? ORDER BY session_ordinal', (question_id,))))

    def keyword_search(self, question_id, query, limit=10):
        """Same exact-token overlap and insertion-order ties as product retrieval.

        Rank individual turns, then keep the first occurrence of each session.
        Scoring uses neither timestamps, labels, reference answers nor query dates.
        """
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            raise ValueError('Limit must be a positive integer.')
        started = time.perf_counter()
        query_words = tokens(query)
        ranked = []
        rows = self.connection.execute('''
            SELECT chunk_id, session_id, turn_ordinal, tokens_json
            FROM benchmark_chunks WHERE question_id=? ORDER BY chunk_id
        ''', (question_id,))
        for row in rows:
            score = len(query_words.intersection(json.loads(row['tokens_json'])))
            if score:
                ranked.append({'chunk_id': row['chunk_id'], 'session_id': row['session_id'],
                               'turn_ordinal': row['turn_ordinal'], 'score': score})
        ranked.sort(key=lambda item: (-item['score'], item['chunk_id']))
        sessions = []
        seen = set()
        for item in ranked:
            if item['session_id'] not in seen:
                sessions.append(item)
                seen.add(item['session_id'])
            if len(sessions) == limit:
                break
        return sessions, (time.perf_counter() - started) * 1000
