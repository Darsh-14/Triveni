"""Tenant -> graph selection. Each tenant is its own FalkorDB graph: `tenant_<name>`.

Isolation comes from FalkorDB itself: a query runs against exactly one graph, so a
query on tenant_acme cannot see tenant_beta. The only rule here is that the tenant
name is validated before it becomes part of a graph key.
"""
import re

from falkordb import Graph

from backend.app.graph.client import get_db

TENANT_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
PREFIX = "tenant_"


class InvalidTenant(ValueError):
    pass


def graph_name(tenant: str) -> str:
    if not isinstance(tenant, str) or not TENANT_RE.fullmatch(tenant):
        raise InvalidTenant(f"invalid tenant name: {tenant!r}")
    return PREFIX + tenant


def get_graph(tenant: str) -> Graph:
    return get_db().select_graph(graph_name(tenant))


def list_tenants() -> list[str]:
    return sorted(g[len(PREFIX):] for g in get_db().list_graphs() if g.startswith(PREFIX))
