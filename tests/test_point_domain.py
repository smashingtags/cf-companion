"""point_domain must be safe in dry-run and must not silently retype records."""

from conftest import FakeCloudflare, FakeRecord, domain_info

TUNNEL = "70b3146b-88c7-4a00-926c-e5b4fe5727a0.cfargotunnel.com"


def test_dry_run_update_logs_and_writes_nothing(cfc, monkeypatch, caplog):
    existing = FakeRecord("rec-1", "old.example.com", "CNAME")
    cf = FakeCloudflare([existing])
    monkeypatch.setattr(cfc, "cf", cf)
    monkeypatch.setattr(cfc, "DRY_RUN", True)
    monkeypatch.setattr(cfc, "RC_TYPE", "CNAME")

    assert cfc.point_domain("app.example.com", [domain_info(TUNNEL)]) is True

    assert cf.dns.records.updated == [], "dry run issued a write"
    assert cf.dns.records.created == [], "dry run issued a write"


def test_dry_run_and_live_take_the_same_decision(cfc, monkeypatch):
    """Dry run must differ from the live run only in whether it writes."""
    doms = [domain_info(TUNNEL)]

    live_cf = FakeCloudflare([FakeRecord("rec-1", "old.example.com", "CNAME")])
    monkeypatch.setattr(cfc, "cf", live_cf)
    monkeypatch.setattr(cfc, "DRY_RUN", False)
    monkeypatch.setattr(cfc, "RC_TYPE", "CNAME")
    assert cfc.point_domain("app.example.com", doms) is True

    dry_cf = FakeCloudflare([FakeRecord("rec-1", "old.example.com", "CNAME")])
    monkeypatch.setattr(cfc, "cf", dry_cf)
    monkeypatch.setattr(cfc, "DRY_RUN", True)
    assert cfc.point_domain("app.example.com", doms) is True

    assert len(live_cf.dns.records.updated) == 1
    assert dry_cf.dns.records.updated == []


def test_dry_run_create_logs_and_writes_nothing(cfc, monkeypatch):
    cf = FakeCloudflare([])
    monkeypatch.setattr(cfc, "cf", cf)
    monkeypatch.setattr(cfc, "DRY_RUN", True)
    monkeypatch.setattr(cfc, "RC_TYPE", "CNAME")

    assert cfc.point_domain("app.example.com", [domain_info(TUNNEL)]) is True
    assert cf.dns.records.created == []


def test_refuses_to_convert_a_tunnel_cname_into_an_a_record(cfc, monkeypatch):
    """The near-miss: RC_TYPE=A against four working proxied tunnel CNAMEs."""
    cf = FakeCloudflare([FakeRecord("rec-1", TUNNEL, "CNAME", proxied=True)])
    monkeypatch.setattr(cfc, "cf", cf)
    monkeypatch.setattr(cfc, "DRY_RUN", False)
    monkeypatch.setattr(cfc, "RC_TYPE", "A")
    monkeypatch.setattr(cfc, "ALLOW_RECORD_TYPE_CHANGE", False)

    cfc.point_domain("app.example.com", [domain_info("76.97.80.164")])

    assert cf.dns.records.updated == [], "overwrote a working tunnel CNAME with an A record"


def test_record_type_change_is_permitted_with_explicit_opt_in(cfc, monkeypatch):
    cf = FakeCloudflare([FakeRecord("rec-1", TUNNEL, "CNAME", proxied=True)])
    monkeypatch.setattr(cfc, "cf", cf)
    monkeypatch.setattr(cfc, "DRY_RUN", False)
    monkeypatch.setattr(cfc, "RC_TYPE", "A")
    monkeypatch.setattr(cfc, "ALLOW_RECORD_TYPE_CHANGE", True)

    cfc.point_domain("app.example.com", [domain_info("76.97.80.164")])

    assert len(cf.dns.records.updated) == 1
    assert cf.dns.records.updated[0][2]["type"] == "A"


def test_same_type_content_change_is_still_applied(cfc, monkeypatch):
    """The guard blocks retyping, not ordinary retargeting."""
    cf = FakeCloudflare([FakeRecord("rec-1", "old.cfargotunnel.com", "CNAME")])
    monkeypatch.setattr(cfc, "cf", cf)
    monkeypatch.setattr(cfc, "DRY_RUN", False)
    monkeypatch.setattr(cfc, "RC_TYPE", "CNAME")
    monkeypatch.setattr(cfc, "ALLOW_RECORD_TYPE_CHANGE", False)

    cfc.point_domain("app.example.com", [domain_info(TUNNEL)])

    assert len(cf.dns.records.updated) == 1
    assert cf.dns.records.updated[0][2]["content"] == TUNNEL
