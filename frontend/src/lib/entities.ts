// One visual identity per node label, shared by the canvas, the legend and the entity chips:
// a shape and a colour, so node types never differ by colour alone.
export type Shape = "round-rectangle" | "ellipse" | "hexagon" | "tag" | "triangle" | "diamond" | "rectangle" | "octagon" | "round-tag";

// Muted, distinct hues (not a stock palette), each at least 3:1 against white; the shape carries the type too.
export const LABEL_STYLE: Record<string, { colour: string; shape: Shape }> = {
  Service: { colour: "#3a6ea5", shape: "round-rectangle" },
  Person: { colour: "#4a7a52", shape: "ellipse" },
  Team: { colour: "#2f5a3a", shape: "hexagon" },
  Deployment: { colour: "#3f7f7a", shape: "tag" },
  Incident: { colour: "#b42318", shape: "triangle" },
  Decision: { colour: "#a8680f", shape: "diamond" },
  Document: { colour: "#6b717a", shape: "rectangle" },
  Episode: { colour: "#6e5a7e", shape: "octagon" },
  Lesson: { colour: "#5d4b6e", shape: "octagon" },
  Procedure: { colour: "#7d6a8c", shape: "octagon" },
  Agent: { colour: "#4b525a", shape: "octagon" },
  Handoff: { colour: "#8a5a6e", shape: "round-tag" },
  Action: { colour: "#7a4a5e", shape: "round-tag" },
  Conversation: { colour: "#5b6b8a", shape: "octagon" },
  Message: { colour: "#7a879e", shape: "octagon" },
};

export const styleOf = (label: string) => LABEL_STYLE[label] ?? { colour: "#9aa1aa", shape: "ellipse" as Shape };

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
