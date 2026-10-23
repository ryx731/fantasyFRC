"""Real HTTP checks against a temporary server/database. No production data used."""
import concurrent.futures
import json
import os
from pathlib import Path
import socket
import threading
import uvicorn
import sys
import tempfile
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError

PROJECT = Path(__file__).resolve().parents[1]

def request(base, path, body=None, token=None, method=None):
    headers = {'Content-Type': 'application/json'}
    if token: headers['Authorization'] = 'Bearer ' + token
    req = Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                  headers=headers, method=method or ('POST' if body is not None else 'GET'))
    try:
        with urlopen(req, timeout=15) as response:
            content = response.read()
            return response.status, json.loads(content) if 'application/json' in response.headers.get('Content-Type','') else content
    except HTTPError as error:
        return error.code, json.loads(error.read())

def run():
    with tempfile.TemporaryDirectory(prefix='fantasy-frc-test-') as temporary:
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
        base = f'http://127.0.0.1:{port}'
        os.environ['DATABASE_URL'] = 'sqlite:///' + str(Path(temporary)/'test.db')
        os.environ['SECRET_KEY'] = 'isolated-http-test-key'
        sys.path.insert(0, str(PROJECT))
        from src.main import app
        from src.database import engine
        server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='error'))
        worker = threading.Thread(target=server.run, daemon=True)
        worker.start()
        try:
            for _ in range(60):
                try:
                    if request(base, '/api/auth/config')[0] == 200: break
                except OSError: time.sleep(0.1)
            else: raise AssertionError('Temporary server did not start')
            assert request(base, '/')[0] == 200
            assert request(base, '/static/app.js')[0] == 200
            assert request(base, '/api/leagues')[0] == 401
            sessions = []
            for name in ('alpha', 'beta', 'outsider'):
                status, data = request(base, '/api/auth/register', {'username': name, 'password': 'test-only-password'})
                assert status == 200, data
                sessions.append(data)
            owner, guest, outsider = [s['access_token'] for s in sessions]
            assert request(base, '/api/admin/overview')[0] == 401
            assert request(base, '/api/admin/overview', token=owner)[0] == 403
            assert request(base, '/api/auth/me', token=owner)[1]['is_admin'] is False
            from sqlalchemy.orm import Session
            from src.models import User
            with Session(engine) as db:
                user = db.query(User).filter_by(username='alpha').one()
                user.is_admin = True
                db.commit()
            status, overview = request(base, '/api/admin/overview', token=owner)
            assert status == 200 and len(overview['users']) == 3
            assert all('hashed_password' not in user for user in overview['users'])
            with Session(engine) as db:
                user = db.query(User).filter_by(username='alpha').one()
                user.is_admin = False
                db.commit()
            assert request(base, '/api/admin/overview', token=owner)[0] == 403
            status, created = request(base, '/api/leagues/create', {'name': 'HTTP league', 'max_teams': 2, 'roster_size': 2, 'starter_count': 1, 'regular_weeks': 1}, owner)
            assert status == 200, created
            lid = created['league_id']; prefix = f'/api/leagues/{lid}'
            assert request(base, prefix, token=outsider)[0] == 403
            assert request(base, prefix+'/join', {}, guest)[0] == 404
            with concurrent.futures.ThreadPoolExecutor(2) as pool:
                results = list(pool.map(lambda t: request(base, '/api/leagues/join', {'code': created['invite_code']}, t)[0], [guest, outsider]))
            assert sorted(results) == [200, 400], results
            guest = guest if results[0] == 200 else outsider
            assert request(base, prefix+'/draft/start', {}, guest)[0] == 403
            assert request(base, prefix+'/draft/start', {}, owner)[0] == 200
            _, home = request(base, prefix, token=owner)
            tokens = {s['user_id']: s['access_token'] for s in sessions}
            picker = tokens[home['draft']['current_picker_id']]
            with concurrent.futures.ThreadPoolExecutor(2) as pool:
                results = list(pool.map(lambda _: request(base, '/api/leagues/draft', {'league_id':lid,'team_number':254}, picker)[0], range(2)))
            assert sorted(results) == [200, 400], results
            for n in (1678, 1690, 4414):
                _, home = request(base, prefix, token=owner)
                status, data = request(base, '/api/leagues/draft', {'league_id':lid,'team_number':n}, tokens[home['draft']['current_picker_id']])
                assert status == 200, data
            _, home = request(base, prefix, token=owner)
            assert home['draft_status'] == 'COMPLETED'
            assert len(home['matchups']) == 1
            scoring = home['scoring']; scoring.pop('preset'); scoring['active'] = True
            assert request(base, prefix+'/scoring', scoring, owner)[0] == 200
            assert request(base, prefix+'/periods/1/open', {}, owner)[0] == 200
            assert request(base, prefix+'/lineup', {'starters':[]}, guest)[0] == 400
            records = [{'match_key':'test_qm1','team_number':t['number'],'metrics':{'auto':3,'teleop':8,'endgame':2,'win':1,'fouls':0}} for r in home['rosters'] for t in r['teams']]
            payload = {'rules_version':scoring['version'],'records':records}
            assert request(base, prefix+'/periods/1/import', payload, owner)[0] == 200
            assert request(base, prefix+'/periods/1/import', payload, owner)[0] == 200
            assert len(request(base, prefix+'/periods/1/scores', token=owner)[1]) == 4
            assert request(base, prefix+'/periods/1/finalize', {}, owner)[0] == 200
            assert request(base, prefix+'/periods/1/import', payload, owner)[0] == 400
            assert request(base, '/openapi.json')[0] == 200
            print('HTTP checks passed: auth, private membership, concurrent capacity, concurrent draft picks, full draft, period locks, idempotent imports, finalization, API schema.')
        finally:
            server.should_exit = True
            worker.join(timeout=10)
            engine.dispose()
            assert not worker.is_alive(), 'Temporary server did not stop'

if __name__ == '__main__': run()
