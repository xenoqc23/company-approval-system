import os
from urllib.request import Request, urlopen

with urlopen('http://127.0.0.1:8000/health/', timeout=5) as response:
    assert response.status == 200 and response.read() == b'ok'
headers = {'X-Forwarded-Proto': 'https'} if os.environ.get('DJANGO_TRUST_PROXY') == '1' else {}
with urlopen(Request('http://127.0.0.1:8000/login/', headers=headers), timeout=5) as response:
    assert response.status == 200 and 'Xenosys'.encode() in response.read()
