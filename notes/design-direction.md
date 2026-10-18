# Triveni design direction

Triveni is an instrument an on-call engineer reads under pressure, closer to an operations logbook or an engineering drawing than to a marketing site. Every visual choice below traces back to that.

1. **Ink on paper.** A cool, near-white page, near-black ink, hairline rules. No gradients, glows, glass, or decorative shadows. Separation comes from rules and spacing, never from border + shadow together.
2. **Type does the work.** IBM Plex Sans for text, IBM Plex Mono for ids, Cypher, numbers and tool names (tabular figures). Body at 400; 500 for labels, 600 only for headings. Labels are sentence case, never small uppercase eyebrows.
3. **Colour only means something.** One accent (river blue, `#24548f`) for focus, selection and the primary action, nothing else. Status colours (ok, warn, bad) only for status. Graph node colours are muted and paired with a shape, so type never depends on colour alone. No track colours: tracks are named in text.
4. **One container level.** An answer is a section of a document, separated by a rule, not a card. Inside it, groups are headings and lists, not nested boxes. No coloured side stripes.
5. **Radius by role.** 2px inline chips, 4px controls, 6px for the one floating dialog, 0 for panes.
6. **No decoration that does not answer a question.** Icons only on controls that would otherwise be ambiguous; entity types use the canvas shape vocabulary instead of an icon set. Dots only for live state; counts are numbers. Motion only for loading.
7. **Specific words.** Labels name the thing ("Owner", "On call", "Superseded"), no marketing verbs, no em-dash prose.
