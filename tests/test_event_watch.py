"""The Docker event watcher must react on a standalone daemon.

A standalone Docker daemon never emits type=service events -- that type only
exists in Swarm. A watcher that filters on it watches forever and reacts to
nothing, which silently degrades reconciliation to startup-only.
"""

from conftest import FakeContainer, FakeDockerClient, domain_info

TRAEFIK_LABELS = {
    "traefik.http.routers.app.rule": "Host(`app.example.com`)",
}


def container_start_event(cont_id="abc123"):
    """The shape a standalone Docker daemon actually emits.

    Captured from Docker Engine 29.7.2 (API 1.55). Modern daemons no longer
    send the legacy top-level "status", "id" and "from" fields -- only Type,
    Action and Actor are present.
    """
    return {
        u"Type": u"container",
        u"Action": u"start",
        u"Actor": {u"ID": cont_id, u"Attributes": {u"name": u"app"}},
        u"scope": u"local",
        u"time": 1756339200,
        u"timeNano": 1756339200000000000,
    }


def legacy_container_start_event(cont_id="abc123"):
    """The pre-API-1.55 shape, still emitted by older daemons."""
    event = container_start_event(cont_id)
    event.update({u"status": u"start", u"id": cont_id, u"from": u"nginx:latest"})
    return event


def service_update_event(service_id="svc123"):
    return {
        u"Type": u"service",
        u"Action": u"update",
        u"Actor": {u"ID": service_id, u"Attributes": {u"name": u"app"}},
        u"scope": u"swarm",
        u"time": 1756339200,
    }


def test_standalone_filters_watch_container_events(cfc):
    filters = cfc.build_event_filters(swarm_mode=False)

    assert "container" in filters.get("type", []), (
        "standalone Docker only emits container events; got %r" % (filters,)
    )
    assert "service" not in filters.get("type", []), (
        "service events do not exist outside Swarm; got %r" % (filters,)
    )
    assert all(key == key.lower() for key in filters), (
        "Docker's event filter keys are lowercase; got %r" % (filters,)
    )


def test_swarm_filters_add_services_without_dropping_containers(cfc):
    filters = cfc.build_event_filters(swarm_mode=True)

    assert "container" in filters.get("type", [])
    assert "service" in filters.get("type", [])


def test_watcher_reacts_to_a_standalone_container_start(cfc, monkeypatch):
    pointed = []
    monkeypatch.setattr(cfc, "point_domain", lambda name, doms: pointed.append(name) or True)
    monkeypatch.setattr(cfc, "TRAEFIK_VERSION", "2")
    monkeypatch.setattr(cfc, "DOCKER_SWARM_MODE", False)

    container = FakeContainer("abc123", TRAEFIK_LABELS)
    client = FakeDockerClient([container_start_event()], {"abc123": container})

    cfc.watch_events(
        [domain_info("tunnel.cfargotunnel.com")],
        docker_client=client,
        swarm_mode=False,
        since="0",
        reconnect=False,
    )

    assert pointed == ["app.example.com"], (
        "watcher did not react to a container start event on standalone Docker"
    )


def test_watcher_survives_a_container_that_vanishes(cfc, monkeypatch):
    """A container that dies before it can be inspected must not stop the watch.

    Otherwise the first race permanently silences reconciliation, which is the
    same symptom the filter bug produced.
    """
    pointed = []
    monkeypatch.setattr(cfc, "point_domain", lambda name, doms: pointed.append(name) or True)
    monkeypatch.setattr(cfc, "TRAEFIK_VERSION", "2")
    monkeypatch.setattr(cfc, "DOCKER_SWARM_MODE", False)

    survivor = FakeContainer("bbb", TRAEFIK_LABELS)
    client = FakeDockerClient(
        [container_start_event("gone"), container_start_event("bbb")],
        {"bbb": survivor},
    )

    cfc.watch_events(
        [domain_info("tunnel.cfargotunnel.com")],
        docker_client=client,
        swarm_mode=False,
        since="0",
        reconnect=False,
    )

    assert pointed == ["app.example.com"]


def test_swarm_service_event_is_still_handled(cfc, monkeypatch):
    pointed = []
    monkeypatch.setattr(cfc, "point_domain", lambda name, doms: pointed.append(name) or True)
    monkeypatch.setattr(cfc, "TRAEFIK_VERSION", "2")
    monkeypatch.setattr(cfc, "check_service_t2", lambda service_id: {"svc.example.com": 1})

    client = FakeDockerClient([service_update_event()])

    cfc.watch_events(
        [domain_info("tunnel.cfargotunnel.com")],
        docker_client=client,
        swarm_mode=True,
        since="0",
        reconnect=False,
    )

    assert pointed == ["svc.example.com"]


def test_watcher_still_handles_the_legacy_event_schema(cfc, monkeypatch):
    """Older daemons send status/id alongside Type/Action. Both must work."""
    pointed = []
    monkeypatch.setattr(cfc, "point_domain", lambda name, doms: pointed.append(name) or True)
    monkeypatch.setattr(cfc, "TRAEFIK_VERSION", "2")
    monkeypatch.setattr(cfc, "DOCKER_SWARM_MODE", False)

    container = FakeContainer("abc123", TRAEFIK_LABELS)
    client = FakeDockerClient([legacy_container_start_event()], {"abc123": container})

    cfc.watch_events(
        [domain_info("tunnel.cfargotunnel.com")],
        docker_client=client,
        swarm_mode=False,
        since="0",
        reconnect=False,
    )

    assert pointed == ["app.example.com"]


def test_noisy_events_are_filtered_out_at_the_daemon(cfc, monkeypatch):
    """The filter must actually narrow the stream, not just ride along."""
    pointed = []
    monkeypatch.setattr(cfc, "point_domain", lambda name, doms: pointed.append(name) or True)
    monkeypatch.setattr(cfc, "TRAEFIK_VERSION", "2")
    monkeypatch.setattr(cfc, "DOCKER_SWARM_MODE", False)

    noise = {
        u"Type": u"container",
        u"Action": u"exec_create: /bin/sh -c healthcheck",
        u"Actor": {u"ID": u"abc123"},
    }
    container = FakeContainer("abc123", TRAEFIK_LABELS)
    client = FakeDockerClient([noise], {"abc123": container})

    cfc.watch_events(
        [domain_info("tunnel.cfargotunnel.com")],
        docker_client=client,
        swarm_mode=False,
        since="0",
        reconnect=False,
    )

    assert pointed == []
