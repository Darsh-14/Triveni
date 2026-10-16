---
id: doc:adr-041
kind: adr
title: "ADR-041: Cap search-api query timeouts at 800 ms"
ts: 2026-10-02T11:00:00Z
author: Dev Malhotra
---
Decision ADR-041, made by Dev Malhotra, status accepted.

search-api and query-suggest must time out queries after 800 ms and return partial results.
Raising these timeouts is not allowed without a new ADR, because slow queries exhausted
search-api threads during the May config-svc incident.
