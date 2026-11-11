"""Bounded JSON/HTTP transport for upstream GUIs and directly connected managers."""
import json
import urllib.error
import urllib.parse
import urllib.request

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def request(url, body=None, timeout=4, text=False):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", "User-Agent": "llama.cpp-Instance-Manager"})
    try:
        with OPENER.open(req, timeout=timeout) as response:
            raw = response.read(8 * 1024 * 1024 + 1)
            if len(raw) > 8 * 1024 * 1024:
                raise ValueError("Response exceeds 8 MB.")
            result = raw.decode("utf-8")
            return result if text else json.loads(result)
    except urllib.error.HTTPError as exc:
        try:
            message = json.loads(exc.read(8192)).get("error", str(exc))
        except (ValueError, AttributeError):
            message = str(exc)
        raise ValueError(str(message)) from exc


def manager_url(value):
    value = str(value or "").strip()
    if "://" not in value:
        value = "http://" + value
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme != "http" or not parsed.hostname or parsed.username or parsed.password or parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ValueError("Enter a manager address such as http://192.168.1.20:5239.")
    port = parsed.port or 5239
    if not 1024 <= port <= 65535:
        raise ValueError("Invalid manager port.")
    host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    return f"http://{host}:{port}"
