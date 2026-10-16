---
id: doc:rb-payments-rollback
kind: runbook
title: "Runbook: rolling back payments-api"
ts: 2026-09-20T09:00:00Z
author: Arjun Mehta
---
payments-api is owned by Team Payments. Arjun Mehta is on call for payments-api.

1. Find the last deployment of payments-api and its author.
2. Roll back to the previous version.
3. Watch connection pool saturation and the checkout error rate for 15 minutes.
4. If errors persist, page the Payments on-call.
