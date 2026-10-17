// One visual identity per node label, shared by the canvas, the legend and the entity chips:
// a shape and a colour, so node types never differ by colour alone.
export type Shape = "round-rectangle" | "ellipse" | "hexagon" | "tag" | "triangle" | "diamond" | "rectangle" | "octagon" | "round-tag";

export const LABEL_STYLE: Record<string, { colour: string; shape: Shape }> = {
  Service: { colour: "#2563eb", shape: "round-rectangle" },
  Person: { colour: "#059669", shape: "ellipse" },
  Team: { colour: "#047857", shape: "hexagon" },
  Deployment: { colour: "#0d9488", shape: "tag" },
  Incident: { colour: "#dc2626", shape: "triangle" },
  Decision: { colour: "#d97706", shape: "diamond" },
  Document: { colour: "#64748b", shape: "rectangle" },
  Episode: { colour: "#7c3aed", shape: "octagon" },
  Lesson: { colour: "#6d28d9", shape: "octagon" },
  Procedure: { colour: "#8b5cf6", shape: "octagon" },
  Agent: { colour: "#475569", shape: "octagon" },
  Handoff: { colour: "#a21caf", shape: "round-tag" },
  Action: { colour: "#9333ea", shape: "round-tag" },
  Conversation: { colour: "#6366f1", shape: "octagon" },
  Message: { colour: "#818cf8", shape: "octagon" },
};

export const styleOf = (label: string) => LABEL_STYLE[label] ?? { colour: "#94a3b8", shape: "ellipse" as Shape };

const PREFIX_LABEL: Record<string, string> = {
  svc: "Service", per: "Person", team: "Team", dep: "Deployment", inc: "Incident", adr: "Decision", dec: "Decision",
  doc: "Document", ep: "Episode", les: "Lesson", lesson: "Lesson", proc: "Procedure", agent: "Agent", hof: "Handoff",
  handoff: "Handoff", act: "Action", action: "Action", conv: "Conversation", msg: "Message",
};

export const labelOfId = (id: string) => PREFIX_LABEL[id.slice(0, id.indexOf(":"))] ?? "Node";

/** Ids as they appear in answers: svc:payments-api, dep:payments-api@2.12.0, adr:019, ... */
export const ID_PATTERN = new RegExp(`\\b(?:${Object.keys(PREFIX_LABEL).join("|")}):[a-z0-9][a-z0-9@._-]*[a-z0-9]`, "gi");

/** Short display name for an id: the part after the prefix. */
export const shortId = (id: string) => id.slice(id.indexOf(":") + 1);

/** Document kind from its id (doc:pm-0042 -> postmortem); the full kind comes from /api/documents. */
export function docKindOfId(id: string): string {
  const s = shortId(id);
  if (s.startsWith("pm-")) return "postmortem";
  if (s.startsWith("adr-")) return "adr";
  if (s.startsWith("rb-")) return "runbook";
  if (s.startsWith("tkt-") || s.startsWith("ticket")) return "ticket";
  if (s.startsWith("chat")) return "chat";
  return "registry";
}
