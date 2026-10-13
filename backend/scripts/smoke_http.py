"""Live local cookie/CSRF attendance demo, using DEMO_PASSWORD from environment only."""
import http.cookiejar
import json
import os
import urllib.request
import urllib.error

base = 'http://localhost:8000/api'
jar = http.cookiejar.CookieJar()
client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

def request(path, data=None, raw=False):
    headers = {'Content-Type':'application/json', 'Origin':'http://localhost:5173'}
    if data is not None:
        token = json.loads(client.open(base+'/auth/csrf/').read())['csrfToken']
        headers['X-CSRFToken'] = token
    req = urllib.request.Request(base+path, data=json.dumps(data).encode() if data is not None else None, headers=headers)
    with client.open(req, timeout=30) as response:
        body = response.read()
        return body if raw else json.loads(body)

password = os.environ['DEMO_PASSWORD']
user = request('/auth/login/', {'username':'teacher','password':password})
assert user['role'] == 'teacher'
sections = request('/sections/')
assert len(sections) == 1, 'teacher scope'
section = sections[0]
session = request(f"/sections/{section['id']}/start/", {'schedule':section['schedules'][-1]['id']})
assert session['checked_in_count'] == 0
student = session['roster'][0]['student']
request(f"/sessions/{session['id']}/manual/", {'student':student,'reason':'Live HTTP demo: teacher verified identity'})
try:
    request(f"/sessions/{session['id']}/manual/", {'student':student,'reason':'Duplicate retry'})
    raise AssertionError('Duplicate allowed')
except urllib.error.HTTPError as exc: assert exc.code == 400
request(f"/sessions/{session['id']}/close/", {})
data = request(f"/sections/{section['id']}/grid/")
assert len(data['students']) == 5
assert request(f"/sections/{section['id']}/export/", raw=True).startswith(b'PK')
assert request(f'/students/{student}/percentages/')
print('LIVE HTTP PASS: cookie login + CSRF, teacher scope, start/manual/duplicate/close, grid, percentages, Excel export.')
