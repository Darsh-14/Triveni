"""Connectivity and load counts against a live FalkorDB."""


def test_connects(db):
    assert db.connection.ping()


def test_loaded_counts_match_generator(loaded, acme, beta):
    for name, (data, _) in (("acme", acme), ("beta", beta)):
        report = loaded["reports"][name]
        derived = sum(report["derived"].values())
        assert report["nodes"] == len(data.nodes)
        assert report["edges"] == len(data.edges) + derived


def test_acme_size(loaded):
    report = loaded["reports"]["acme"]
    assert 250 <= report["nodes"] <= 350
    assert 1100 <= report["edges"] <= 1800


def test_node_properties_survive_load(loaded):
    """Checks `SET n += row` stores arrays and scalars as-is."""
    row = loaded["acme"].ro_query(
        "MATCH (d:Decision {id: $id}) RETURN d.forbids, d.status", {"id": "adr:019"}
    ).result_set[0]
    assert row == [["change_retry_policy"], "accepted"]


def test_state_edges_carry_temporal_props(loaded):
    for rel in ("OWNS", "MEMBER_OF", "ON_CALL_FOR", "DEPENDS_ON"):
        bad = loaded["acme"].ro_query(
            f"MATCH ()-[r:{rel}]->() WHERE r.valid_from IS NULL OR r.source_doc IS NULL RETURN count(r)"
        ).result_set[0][0]
        assert bad == 0, rel
