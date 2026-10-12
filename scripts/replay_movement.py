"""Read-only production-rule replay; does not migrate or modify the database."""
import argparse
import json
import sqlite3
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.movement_diagnostics import replay

class ReadOnlyStore:
    def __init__(self,path):
        self.db=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)
        self.db.row_factory=sqlite3.Row
    def rows(self,sql,args=()):return self.db.execute(sql,args).fetchall()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--db',default='data/radar.sqlite3');p.add_argument('--symbol',required=True);p.add_argument('--date',required=True);p.add_argument('--start',default='09:30');p.add_argument('--end',default='11:03');p.add_argument('--output',required=True)
    a=p.parse_args()
    from app.domain.market import symbol_id
    s=ReadOnlyStore(a.db)
    try:result=replay(s,symbol_id(a.symbol),a.date,a.start,a.end)
    finally:s.db.close()
    Path(a.output).write_text(json.dumps(result,ensure_ascii=False,indent=2))
