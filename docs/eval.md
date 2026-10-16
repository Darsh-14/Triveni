# Eval: Triveni vs flat baseline

Run 2026-10-16 12:48 UTC (re-scored) with `python -m backend.scripts.eval`. 15 questions, 5 per track (notes/eval-questions.md). Ground truth comes from the seed generator, never from either system. Both systems use the **same model**: groq:openai/gpt-oss-120b. One run, so expect some run-to-run noise.

- **Triveni:** the triage agent choosing graph tools over MCP, with memory (episodes, conversation history).
- **Flat baseline:** TF-IDF over passages (~400 chars) of the same tenant's documents, top 8, then the same model. No graph, no memory. It sees the same documents Triveni ingested, including the Scenario 7 chat.

**Scoring:** each answer ends with an `ENTITIES:` line, normalised to graph ids. An answer is correct when it contains every expected entity and its only extras are entities the question itself names (restating the subject, e.g. `svc:orders-api` in "retry policy on orders-api", is not a wrong answer). The same rule scores both systems. Mean F1 is shown for partial credit. Evidence = the answer is backed by tool provenance (Triveni) or cites a retrieved document (baseline).

| Track | System | Correct | Mean F1 | Answers with evidence | Median latency | Tokens / answer |
|---|---|---|---|---|---|---|
| 01 Act | Triveni | 5/5 | 0.93 | 100% | 12.4 s | 5544 |
| 01 Act | Flat baseline | 1/5 | 0.45 | 60% | 1.7 s | 1519 |
| 02 Remember & Coordinate | Triveni | 5/5 | 0.93 | 80% | 11.0 s | 4865 |
| 02 Remember & Coordinate | Flat baseline | 0/5 | 0.00 | 60% | 1.9 s | 1161 |
| 03 Company Brain | Triveni | 5/5 | 1.00 | 100% | 6.6 s | 5535 |
| 03 Company Brain | Flat baseline | 3/5 | 0.60 | 60% | 1.3 s | 1027 |

## Per question

| Q | Expected | Triveni | Baseline | Triveni tools |
|---|---|---|---|---|
| A1: If payments-api goes down, which services are affected within 3 hops? | svc:cart-api, svc:checkout-web, svc:invoice-svc, svc:orders-api, svc:refund-worker | ✅ svc:cart-api, svc:checkout-web, svc:invoice-svc, svc:orders-api, svc:refund-worker | ❌ svc:invoice-svc, svc:orders-api | blast_radius |
| A2: What is the shortest dependency path from checkout-web to payments-api? List every service on it. | svc:cart-api, svc:checkout-web, svc:orders-api, svc:payments-api | ✅ svc:cart-api, svc:checkout-web, svc:orders-api, svc:payments-api | ❌ (none) | shortest_path |
| A3: Which 3 services are most critical by dependency structure (most depended upon)? | svc:catalog-sync, svc:email-sender, svc:referral-svc | ✅ svc:catalog-sync, svc:email-sender, svc:referral-svc | ❌ svc:email-sender, svc:ranking-svc, svc:referral-svc | critical_services |
| A4: Which services have no owning team and no on-call engineer? | svc:legacy-fax-gateway, svc:pdf-renderer-v1 | ✅ svc:legacy-fax-gateway, svc:pdf-renderer-v1 | ❌ (none) | find_orphans |
| A5: Can we change the retry policy on orders-api? If not, which decision blocks it? | adr:019 | ✅ adr:019, svc:orders-api | ✅ adr:019 | decision_trail |
| B1: payments-api has connection timeouts again. Have we seen this before? Which past episode and which procedure apply? | ep:0001, proc:rollback-payments | ✅ ep:0001, proc:rollback-payments | ❌ doc:pm-0042, doc:tkt-0042, svc:payments-api | recall |
| B2: What lesson did we learn the last time payments-api failed? | lesson:pool-exhaustion | ✅ lesson:pool-exhaustion | ❌ svc:payments-api | recall |
| B3: orders-api is slow again. Which procedure worked before? | proc:c55a5e4bd0d2 | ✅ proc:c55a5e4bd0d2, svc:orders-api | ❌ adr:007, rb-orders-retry | recall |
| B4: Which open handoffs are waiting for the remediation agent, and about which incident? | handoff:c2a9a64098ac, inc:0057 | ✅ handoff:c2a9a64098ac, inc:0057 | ❌ (none) | list_handoffs |
| B5: What team did I say I'm on? | team:payments | ✅ team:payments | ❌ (none) |  |
| C1: Who owns payments-api and who is on call for it? | per:arjun-mehta, team:payments | ✅ per:arjun-mehta, team:payments | ✅ per:arjun-mehta, team:payments | owner_of |
| C2: Which decision governs orders-api today, and which earlier decision did it replace? | adr:007, adr:019 | ✅ adr:007, adr:019 | ✅ adr:007, adr:019 | decision_trail |
| C3: Who are the two engineers whose departure would cut knowledge links between teams? | per:dev-malhotra, per:priya-nair | ✅ per:dev-malhotra, per:priya-nair | ❌ (none) | key_people |
| C4: Who owns billing-batch now, and who owned it before? | team:atlas, team:ledger | ✅ team:atlas, team:ledger | ✅ team:atlas, team:ledger | owner_of |
| C5: Which runbooks are out of date for the services Team Atlas now owns? | doc:rb-billing-rerun | ✅ doc:rb-billing-rerun | ❌ (none) | team_services |

Models used: Flat baseline: groq:openai/gpt-oss-120b; Triveni: groq:openai/gpt-oss-120b

Notes: B5 is answered from the conversation history the agent loads from the graph, so it has no tool step (hence Triveni's 80% evidence on Track 02). C1 is a control question the flat baseline is expected to answer (both owner and on-call are stated in registry documents).
