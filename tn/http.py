"""HTTP minimale con retry/backoff. Le API gratuite throttolano: qui si riprova
e si restituisce l'ultimo errore solo dopo N tentativi."""
import json
import time
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (trading-news-ai)"}


def fetch(url, headers=None, timeout=25, tries=4, data=None):
    h = dict(UA)
    if headers:
        h.update(headers)
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=data, headers=h)
            return urllib.request.urlopen(req, timeout=timeout).read()
        except Exception as e:
            last = e
            time.sleep(1.2 * (i + 1))
    raise last


def get_json(url, headers=None, timeout=25, tries=4):
    return json.loads(fetch(url, headers=headers, timeout=timeout, tries=tries))


def post_json(url, payload, headers=None, timeout=25, tries=4):
    h = {"Content-Type": "application/json"}
    if headers:
        h.update(headers)
    raw = fetch(url, headers=h, timeout=timeout, tries=tries,
                data=json.dumps(payload).encode())
    return json.loads(raw)
