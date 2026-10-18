// One visual identity per node label, shared by the canvas, the legend and the entity chips:
// a shape and a colour, so node types never differ by colour alone.
export type Shape = "round-rectangle" | "ellipse" | "hexagon" | "tag" | "triangle" | "diamond" | "rectangle" | "octagon" | "round-tag";

// From the "mono neon picnic" families only: olive and ash for systems and teams, almond for people and decisions,
// fuchsia for incidents (the one neon thing) and the agent's memory. The shape carries the type too.
export const LABEL_STYLE: Record<string, { colour: string; shape: Shape }> = {
  Service: { colour: "#aeb3a0", shape: "round-rectangle" },   // dusty olive
  Team: { colour: "#e4e6df", shape: "hexagon" },              // dusty olive 200
  Person: { colour: "#da9384", shape: "ellipse" },            // almond silk 300
  Deployment: { colour: "#999b7a", shape: "tag" },            // ash grey 300
  Incident: { colour: "#ff1053", shape: "triangle" },         // hot fuchsia
  Decision: { colour: "#c65741", shape: "diamond" },          // almond silk 200
  Document: { colour: "#999999", shape: "rectangle" },        // black 700
  Episode: { colour: "#ff6f98", shape: "octagon" },           // hot fuchsia 200
  Lesson: { colour: "#efd0ca", shape: "octagon" },            // almond silk 100
  Procedure: { colour: "#ff3f76", shape: "octagon" },         // hot fuchsia 300
  Agent: { colour: "#cccccc", shape: "octagon" },             // black 600
  Handoff: { colour: "#939980", shape: "round-tag" },         // dusty olive 300
  Action: { colour: "#ff9fba", shape: "round-tag" },          // hot fuchsia 400
  Conversation: { colour: "#c6c7b5", shape: "octagon" },      // ash grey 200
  Message: { colour: "#757759", shape: "octagon" },           // ash grey 300
};

export const styleOf = (label: string) => LABEL_STYLE[label] ?? { colour: "#777777", shape: "ellipse" as Shape };

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
