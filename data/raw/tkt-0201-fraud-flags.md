---
id: doc:tkt-0201
kind: ticket
title: "TKT-201: fraud-scorer reads model rollout flags"
ts: 2026-10-13T10:15:00Z
author: Kavya Rao
---
fraud-scorer now depends on feature-flags: the new scoring model is rolled out behind a flag,
so fraud-scorer calls feature-flags on every request. Add the dependency to the service catalog
and make sure feature-flags alerts page Payments as well.
