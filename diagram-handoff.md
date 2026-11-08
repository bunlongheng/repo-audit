# Diagram Handoff (moved from repo-recon/SKILL.md on 2026-11-08)


Every recon of a repo produces 3 diagram artifacts, in this order:

**1. Flows picture (rendered, NEVER stored - owner rule 2026-10-04).** Map the
recon's architecture read (entrypoints, key modules, external systems from
"How it works") onto valid service ids per `/create-flow`'s concept-to-service
table (`list_services` is authoritative - never invent an id). Then ask for the
picture only: an audit diagram must never appear in the owner's gallery, so
every call carries `source: "repo-audit"`, the marker the API and MCP use to
render and store nothing.
- MCP available (`flows` server, personal Mac): `create_flow`
  with `{title: "<owner/repo> - Architecture", source: "repo-audit", nodes, edges, lanes}`
  -> returns `{stored: false, svg}`. Layers (client, API, data, infra) go in the
  SAME call as `lanes`: columns `{id, title, x, w, color?}` for a left-to-right
  layout, rows `{id, title, y, h, color?}` for a top-down one. There is no id,
  url or gif, and nothing to update afterwards.
- No MCP (work Mac): curl fallback `POST https://flows-bheng.vercel.app/api/ai/flows`
  with `Authorization: Bearer $FLOWS_API_SECRET` and the same body including
  `"source": "repo-audit"` -> `200 {stored: false, svg}`. If the secret is not
  in env on this machine, SKIP gracefully - still do artifacts 2 and 3, and
  print the ready-to-post payload JSON so the picture can be rendered from the M4 later.
- Never omit `source`. A call without it STORES a row, and stored audit rows are
  what the owner removed on 2026-10-04.
- Same marker in the sibling apps: if a run ever asks Mindmaps
  (`create_mindmap` / `POST /api/ai/mindmaps`) or Sequences (`create_sequence` /
  `POST /api/ai/sequences`) for a picture, it carries `source: "repo-audit"`
  there too. All 3 apps read that one field and none of them guesses from the
  title - an audit is known by what it declares it is, never by what it is
  called. What they DO with it differs, so read the answer:
  - Flows and Mindmaps never store: `200 {stored: false, svg}`, no id, no url.
  - Sequences does not store either: `200 {stored: false, source, svg}`, no id,
    no url, no canvas. Its `/api/sequences` POST - the one door with no renderer
    wired - is the exception: an audit source there is stored but tagged
    `repo-audit` and filtered out of the library list. Ask `/api/ai/sequences`
    and that never comes up.
- The old rows ("<repo> Features (repo-audit)" in Mindmaps, "<repo> - File
  Layers" in Sequences, "<owner>/<repo> - Architecture (repo-audit)" in Flows)
  were deleted on 2026-10-04 - 74 of them.

**2. Embed in the HTML report (-> Stickies).** The report gets a "Flows"
card near the architecture section containing the svg itself, self-contained:
`<img src="data:image/svg+xml;base64,<base64 of svg>" style="width:100%;height:auto;border:1px solid #e5e7eb;border-radius:12px" alt="<repo> architecture">`
(base64 so Stickies' sanitiser cannot strip inline svg). No link, no iframe:
there is no page to link to. If rendering was skipped (no key on this
machine), the card shows the payload JSON in a `<pre>` block instead, labeled
"render from M4".

**3. Gemini prompt (always, no dependency).** A copy-paste prompt block in the
report (`<pre>` card titled "Gemini diagram prompt") AND in the chat summary,
so the user can generate a polished image version in Gemini. Template:

```
Draw a clean system architecture diagram for <repo>.
Style: white background, rounded card nodes with real product logos, thin
labeled arrows, section bands with small uppercase titles, red X overlay on
anything being decommissioned, dashed green arrows for planned migrations,
dashed red outline + "?" for undefined components.
Sections: <one line per section - name + the nodes in it>.
Flows: <one line per arrow - "A -> B: label">.
Callouts: <badges/warnings, e.g. security notes, TBD items>.
```
Fill every `<...>` from the actual recon data - never ship the template raw.

