"""Persistent fictional pending documents for the PC-login trial only."""
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

SAMPLES = [
    ('trial-leave', '휴가원', '홍길동', '개발팀', '대리'),
    ('trial-purchase', '구매요청서', '김가영', '생산팀', '과장'),
]


class PendingStore:
    def __init__(self, path, clock=time.time):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY, kind TEXT NOT NULL, author TEXT NOT NULL,
                    department TEXT NOT NULL, rank TEXT NOT NULL,
                    created REAL NOT NULL, completed REAL
                );
                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY, created REAL NOT NULL, reason TEXT NOT NULL,
                    count INTEGER NOT NULL, result TEXT NOT NULL, message TEXT NOT NULL
                );
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def create_samples(self):
        with self.connect() as db:
            db.executemany('''INSERT INTO documents(id, kind, author, department, rank, created)
                VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET completed=NULL, created=excluded.created''',
                [(*row, self.clock()) for row in SAMPLES])

    def documents(self, pending_only=False):
        with self.connect() as db:
            rows = db.execute('SELECT * FROM documents' + (' WHERE completed IS NULL' if pending_only else '') + ' ORDER BY created, id').fetchall()
            return [dict(row) for row in rows]

    def complete(self, document_id):
        with self.connect() as db:
            found = db.execute('SELECT id FROM documents WHERE id=?', (document_id,)).fetchone()
            if not found:
                raise ValueError('해당 가상 문서가 없습니다. 목록을 새로고침해 주세요.')
            db.execute('UPDATE documents SET completed=COALESCE(completed, ?) WHERE id=?', (self.clock(), document_id))

    def record(self, reason, count, result, message):
        with self.connect() as db:
            db.execute('INSERT INTO reminders(created, reason, count, result, message) VALUES (?, ?, ?, ?, ?)',
                       (self.clock(), reason, count, result, message[:700]))

    def status(self):
        docs = self.documents()
        with self.connect() as db:
            last = db.execute('SELECT * FROM reminders ORDER BY id DESC LIMIT 1').fetchone()
        return dict(documents=docs, pending_count=sum(d['completed'] is None for d in docs),
                    last_reminder=dict(last) if last else None)


def remind_once(store, desktop, reason='manual_test'):
    """Never mark a document completed merely because an alert was requested."""
    rows = store.documents(pending_only=True)
    if not rows:
        result = dict(result='empty', message='처리할 가상 문서가 없어 알림을 띄우지 않았습니다.', count=0)
    else:
        lines = [f'{d["department"]} {d["author"]} {d["rank"]} · {d["kind"]}' for d in rows[:3]]
        try:
            desktop.notify(f'[테스트] 처리할 결재 문서 {len(rows)}건', '\n'.join(lines))
            result = dict(result='requested', message='Windows에 미결 알림 표시를 요청했습니다. 오른쪽 아래와 알림 센터를 확인해 주세요.', count=len(rows))
        except (OSError, RuntimeError) as exc:
            result = dict(result='failed', message=str(exc), count=len(rows))
    store.record(reason, result['count'], result['result'], result['message'])
    return result
