# Devlog

Running notes; feeds the blog post. Newest at the bottom.

## Oct 16
- Local Docker blocked: WSL2 can't start on the dev laptop (Windows component store is missing the Virtual Machine Platform manifests; DISM repair from Windows Update and from an ISO both failed). Moved development to FalkorDB Cloud; `docker-compose.yml` stays as the reference local setup.
- Checked the `falkordb` Python client (1.8.0) API directly: `FalkorDB(host, port, username, password, ssl)`, `select_graph`, `list_graphs`, `Graph.query/ro_query(q, params)`, `create_node_range_index(label, *props)`.
- Scaffold: package, config, compose file, README skeleton with a section per track.
