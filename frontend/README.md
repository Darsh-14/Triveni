# Triveni UI

Next.js 16 + TypeScript + Tailwind + Cytoscape.js. Talks only to the FastAPI backend.

```bash
npm install
npm run dev            # http://localhost:3001  (port 3000 is left for FalkorDB Browser)
```

Set `NEXT_PUBLIC_TRIVENI_API` (default `http://localhost:8000`) to point at another backend.

- Left: demo scenarios, ask the agent (needs `ANTHROPIC_API_KEY` on the backend) or run any graph tool directly.
- Each answer: track badges, the tool plan (tool, input, why, time), a **Cypher** button per step, clickable sources.
- Centre: graph canvas. The overview shows services and owning teams; selecting an answer shows exactly the
  nodes and edges in its evidence paths (superseded/stale edges dashed red).
