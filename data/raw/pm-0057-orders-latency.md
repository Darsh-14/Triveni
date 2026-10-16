---
id: doc:pm-0057
kind: postmortem
title: "Postmortem: orders-api p99 latency spike (inc:0057)"
ts: 2026-10-15T13:00:00Z
author: Vikram Shah
---
Incident inc:0057, orders-api p99 latency above 4s on Oct 15.

Vikram Shah resolved the incident at 12:40 UTC by scaling the orders-api worker pool from 8 to 20 workers.
The worker pool had not been resized after the September traffic growth.

Retries stayed frozen at 2 attempts per ADR-019, which kept the slowdown from turning into a retry storm
against payments-api. Follow-up: add autoscaling on queue depth.
