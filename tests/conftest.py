import importlib.util
import pathlib
import sys

import docker.errors
import pytest

APP = pathlib.Path(__file__).resolve().parents[1] / "app" / "cloudflare-companion.py"


@pytest.fixture
def cfc(monkeypatch):
    """A freshly imported copy of the companion module.

    The file name is not a legal module name, so it is loaded by path. A fresh
    copy per test keeps the module-level configuration globals isolated.
    """
    monkeypatch.setenv("LOG_TYPE", "CONSOLE")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")

    spec = importlib.util.spec_from_file_location("cloudflare_companion", APP)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


class FakeContainer:
    def __init__(self, cont_id, labels):
        self.attrs = {u"Id": cont_id, u"Config": {u"Labels": labels}}


class FakeContainers:
    def __init__(self, by_id):
        self._by_id = by_id

    def get(self, cont_id):
        try:
            return self._by_id[cont_id]
        except KeyError:
            raise docker.errors.NotFound("no such container: %s" % cont_id)

    def list(self):
        return list(self._by_id.values())


# Filter keys the Docker daemon recognises on GET /events. Anything else is
# silently ignored by the daemon -- it does NOT error and it does NOT narrow
# the stream. Verified against Docker Engine 29.7.2 (API 1.55).
KNOWN_EVENT_FILTER_KEYS = {
    "config", "container", "daemon", "event", "image", "label", "network",
    "node", "plugin", "scope", "secret", "service", "type", "volume",
}


class FakeDockerClient:
    """Stands in for docker.DockerClient over the read-only socket proxy.

    Only the calls the proxy actually exposes are implemented: /containers/json,
    /containers/{id}/json and /events. Filter handling mirrors the real daemon,
    including its habit of ignoring filter keys it does not recognise.
    """

    def __init__(self, events, containers=None):
        self._events = events
        self.containers = FakeContainers(containers or {})
        self.recorded_filters = []

    @staticmethod
    def _matches(event, filters):
        for key, values in (filters or {}).items():
            if key not in KNOWN_EVENT_FILTER_KEYS:
                continue
            if isinstance(values, str):
                values = [values]
            if key == "type" and event.get("Type") not in values:
                return False
            if key == "event" and event.get("Action") not in values:
                return False
        return True

    def events(self, since=None, filters=None, decode=True):
        self.recorded_filters.append(filters)
        return iter([e for e in self._events if self._matches(e, filters)])


class FakeRecord:
    def __init__(self, record_id, content, record_type="CNAME", proxied=True):
        self.id = record_id
        self.content = content
        self.type = record_type
        self.proxied = proxied


class FakeRecordsResponse:
    def __init__(self, result):
        self.result = result


class FakeRecordsAPI:
    def __init__(self, existing):
        self._existing = existing
        self.created = []
        self.updated = []

    def list(self, zone_id=None, name=None):
        return FakeRecordsResponse(list(self._existing))

    def create(self, zone_id=None, **data):
        self.created.append((zone_id, data))
        return FakeRecord("new-id", data.get("content"), data.get("type"))

    def update(self, zone_id=None, dns_record_id=None, **data):
        self.updated.append((zone_id, dns_record_id, data))
        return FakeRecord(dns_record_id, data.get("content"), data.get("type"))


class FakeDNS:
    def __init__(self, records):
        self.records = records


class FakeCloudflare:
    def __init__(self, existing=()):
        self.dns = FakeDNS(FakeRecordsAPI(list(existing)))


def domain_info(target_domain, name="example.com", proxied=True, ttl=1):
    return {
        "name": name,
        "proxied": proxied,
        "zone_id": "zone123",
        "ttl": ttl,
        "target_domain": target_domain,
        "comment": None,
        "excluded_sub_domains": [],
    }
