import hashlib,json,sqlite3,time
from contextlib import closing
from pathlib import Path
SCHEMA='''CREATE TABLE IF NOT EXISTS strategies(id TEXT PRIMARY KEY,generation INTEGER,parent_id TEXT,prompt TEXT,metadata TEXT,created REAL);CREATE TABLE IF NOT EXISTS runs(id INTEGER PRIMARY KEY AUTOINCREMENT,strategy_id TEXT,started REAL,finished REAL,summary TEXT);CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT,ts REAL,kind TEXT,payload TEXT);CREATE TABLE IF NOT EXISTS champions(generation INTEGER PRIMARY KEY,strategy_id TEXT,ts REAL);'''
class EvidenceStore:
    def __init__(self,path:Path):
        self.path=path;path.parent.mkdir(parents=True,exist_ok=True)
        with closing(sqlite3.connect(path)) as c:c.executescript(SCHEMA);c.commit()
    def event(self,kind,payload):
        with closing(sqlite3.connect(self.path)) as c:c.execute('INSERT INTO events(ts,kind,payload) VALUES(?,?,?)',(time.time(),kind,json.dumps(payload,sort_keys=True)));c.commit()
    def save_strategy(self,s):
        metadata={**s.metadata,'prompt_sha256':hashlib.sha256(s.system_prompt.encode()).hexdigest()}
        values=(s.id,s.generation,s.parent_id,s.system_prompt,json.dumps(metadata,sort_keys=True))
        with closing(sqlite3.connect(self.path)) as c:
            old=c.execute('SELECT id,generation,parent_id,prompt,metadata FROM strategies WHERE id=?',(s.id,)).fetchone()
            if old is not None and old != values:raise ValueError('immutable strategy ID cannot be overwritten')
            if old is None:c.execute('INSERT INTO strategies VALUES(?,?,?,?,?,?)',(*values,time.time()))
            c.commit()
    def save_summary(self,summary,started):
        with closing(sqlite3.connect(self.path)) as c:c.execute('INSERT INTO runs(strategy_id,started,finished,summary) VALUES(?,?,?,?)',(summary.strategy_id,started,time.time(),json.dumps(summary.to_dict(),sort_keys=True)));c.commit()
    def promote(self,generation,strategy_id):
        with closing(sqlite3.connect(self.path)) as c:c.execute('INSERT OR REPLACE INTO champions VALUES(?,?,?)',(generation,strategy_id,time.time()));c.commit()
        self.event('promotion',{'generation':generation,'strategy_id':strategy_id})
    def latest(self):
        with closing(sqlite3.connect(self.path)) as c:
            c.row_factory=sqlite3.Row;return [dict(r) for r in c.execute('SELECT * FROM runs ORDER BY id DESC LIMIT 20').fetchall()]
    def export(self):
        with closing(sqlite3.connect(self.path)) as c:
            c.row_factory=sqlite3.Row
            return {t:[dict(r) for r in c.execute(f'SELECT * FROM {t} ORDER BY rowid').fetchall()] for t in ('strategies','runs','events','champions')}
