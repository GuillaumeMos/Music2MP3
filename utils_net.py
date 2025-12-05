# utils_net.py
import requests, time
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

def retrying_session(
    total=5, backoff_factor=0.5,
    status_forcelist=(429, 500, 502, 503, 504),
    methods=frozenset(["HEAD","GET","OPTIONS"])
):
    s = requests.Session()
    r = Retry(
        total=total, read=total, connect=total,
        status_forcelist=status_forcelist,
        allowed_methods=methods, backoff_factor=backoff_factor,
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    s.mount("https://", HTTPAdapter(max_retries=r))
    s.mount("http://", HTTPAdapter(max_retries=r))
    s.request = _with_timeout(s.request)  # inject default timeout
    return s

def _with_timeout(fn, default_timeout=20):
    def wrapped(method, url, **kw):
        kw.setdefault("timeout", default_timeout)
        return fn(method, url, **kw)
    return wrapped
