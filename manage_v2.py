"""Offline database inspection and backup restoration; never imports the app."""
import argparse
from contextlib import closing
from datetime import datetime
import json
from pathlib import Path
import sqlite3


def readonly(path):
    path=Path(path).expanduser().resolve()
    if not path.is_file():raise ValueError('Database file does not exist: '+str(path))
    return sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)


def inspect(path):
    with closing(readonly(path)) as conn:
        conn.row_factory=sqlite3.Row
        names={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        tables=['customers','health_assessments','appointments','home_appointments','service_improvement_records','equipment','therapy_projects','v2_services','v2_reviews','v2_screenings','v2_measurements','v2_surveys','v2_tasks','v2_archive']
        return {'database':str(Path(path).resolve()),'integrity':conn.execute('PRAGMA integrity_check').fetchone()[0],
                'foreign_key_errors':[tuple(r) for r in conn.execute('PRAGMA foreign_key_check')],
                'counts':{t:conn.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in tables if t in names},
                'migrations':[dict(r) for r in conn.execute('SELECT * FROM v2_migrations ORDER BY id')] if 'v2_migrations' in names else [],
                'pending_aliases':[dict(r) for r in conn.execute("SELECT p.name,l.proposed_code FROM v2_project_links l JOIN therapy_projects p ON p.id=l.legacy_project_id WHERE l.state='pending'")] if 'v2_project_links' in names else []}


def restore(source,target,stopped=False):
    if not stopped:raise ValueError('Stop every application process first, then pass --server-stopped.')
    source=Path(source).resolve();target=Path(target).resolve()
    if source==target:raise ValueError('Backup source must differ from the target database.')
    if not target.is_file():raise ValueError('Target database does not exist; check --data-dir.')
    report=inspect(source)
    if report['integrity']!='ok':raise ValueError('Backup failed the integrity check.')
    folder=target.parent/'database_backups';folder.mkdir(exist_ok=True)
    safety=folder/('before_restore_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.db')
    with closing(sqlite3.connect(target,timeout=2)) as current:
        # Fail early when another process has a write transaction. The explicit flag also
        # covers idle application processes, which SQLite cannot identify reliably.
        current.execute('BEGIN EXCLUSIVE');current.rollback()
        with closing(sqlite3.connect(safety)) as copy:current.backup(copy)
        with closing(readonly(source)) as backup:backup.backup(current)
    return {'restored_from':str(source),'target':str(target),'preserved_current':str(safety),'verification':inspect(target)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['inspect','restore'])
    parser.add_argument('--data-dir',default=str(Path(__file__).resolve().parent))
    parser.add_argument('--backup')
    parser.add_argument('--server-stopped',action='store_true')
    args=parser.parse_args();target=Path(args.data_dir)/'medical_system.db'
    try:
        if args.command=='restore' and not args.backup:raise ValueError('--backup is required for restore.')
        result=inspect(target) if args.command=='inspect' else restore(args.backup,target,args.server_stopped)
        print(json.dumps(result,ensure_ascii=True,indent=2));return 0
    except (ValueError,sqlite3.Error,OSError) as error:
        print('Database operation failed: '+str(error));return 1


if __name__=='__main__':raise SystemExit(main())
