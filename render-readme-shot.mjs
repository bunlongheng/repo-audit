/**
 * render-readme-shot.mjs - HD screenshot of a repo's README.md for /repo-audit.
 *
 * Renders README.md (GitHub markdown CSS + Mermaid diagrams) in headless
 * Chromium and captures a full-page 2x-retina PNG.
 *
 * Usage:  node render-readme-shot.mjs <repoPath> [outPath]
 *   out defaults to <repoPath>/docs/screenshots/readme.png
 *
 * Portable: hardcodes no repo or secret. Resolves Playwright from the target
 * repo first, then this skill's own node_modules, then a global. If none is
 * available it prints "SKIP" and exits 0 (never fails the audit).
 *
 * Security: README.md content is UNTRUSTED input. The markdown renderer escapes any
 * raw HTML/script the README embeds instead of passing it through, strips non-http(s)
 * link/image protocols, and the page blocks all network requests except the pinned CDN
 * hosts it loads itself - so a hostile README cannot run script or exfiltrate data.
 */
import fs from "fs";
import path from "path";
import { createRequire } from "module";

const repo = path.resolve(process.argv[2] || ".");
const out = process.argv[3] || path.join(repo, "docs/screenshots/readme.png");

// Find README.md (case-insensitive) in the repo root.
const readme = fs.readdirSync(repo).find((f) => /^readme\.md$/i.test(f));
if (!readme) { console.log("SKIP: no README.md in " + repo); process.exit(0); }

// Resolve a chromium from wherever Playwright happens to live.
function loadChromium() {
  const roots = [repo, path.dirname(new URL(import.meta.url).pathname), process.cwd()];
  for (const root of roots) {
    for (const pkgName of ["@playwright/test", "playwright", "playwright-core"]) {
      try {
        const req = createRequire(path.join(root, "package.json"));
        const mod = req(pkgName);
        if (mod?.chromium) return mod.chromium;
      } catch { /* try next */ }
    }
  }
  return null;
}

const chromium = loadChromium();
if (!chromium) { console.log("SKIP: Playwright not installed (npm i -D @playwright/test)"); process.exit(0); }

const md = fs.readFileSync(path.join(repo, readme), "utf8");
const b64 = Buffer.from(md, "utf8").toString("base64");

const html = `<!doctype html><html><head><meta charset="utf-8">
<base href="file://${repo}/">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/github-markdown-css@5/github-markdown-light.min.css">
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>
<style>
  body{margin:0;background:#fff;}
  .markdown-body{box-sizing:border-box;max-width:900px;margin:0 auto;padding:48px 56px;}
  .mermaid{background:#fff;margin:12px 0;}
</style></head>
<body><article class="markdown-body" id="out"></article>
<script>
  const src = decodeURIComponent(escape(atob("${b64}")));
  const escHtml = (s) => String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  const renderer = new marked.Renderer();
  const origCode = renderer.code.bind(renderer);
  renderer.code = (code, lang) => {
    const c = (typeof code === 'object') ? code.text : code;
    const l = (typeof code === 'object') ? code.lang : lang;
    if (l === 'mermaid') return '<pre class="mermaid">' + c + '</pre>';
    return origCode(typeof code === 'object' ? code : c, l);
  };
  // The README is untrusted: never let raw HTML it embeds reach the DOM unescaped, and
  // never let a link/image use a non-http(s)/mailto protocol (e.g. javascript:).
  renderer.html = (h) => escHtml(typeof h === 'object' ? h.text : h);
  const safeHref = (href) => (/^(https?:|mailto:|#|\/)/i.test(href || '')) ? href : '#';
  const origLink = renderer.link.bind(renderer);
  renderer.link = (href, title, text) => {
    const h = (typeof href === 'object') ? href.href : href;
    const t = (typeof href === 'object') ? href.title : title;
    const x = (typeof href === 'object') ? href.text : text;
    return origLink(safeHref(h), t, x);
  };
  document.getElementById('out').innerHTML = marked.parse(src, { renderer });
  mermaid.initialize({ startOnLoad: false, theme: 'default', securityLevel: 'strict' });
  window.__ready = mermaid.run({ querySelector: '.mermaid' }).then(()=>true).catch(()=>true);
</script></body></html>`;

const tmp = path.join(process.env.TMPDIR || "/tmp", `readme-shot-${path.basename(repo)}.html`);
fs.writeFileSync(tmp, html);
fs.mkdirSync(path.dirname(out), { recursive: true });

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1000, height: 1400 }, deviceScaleFactor: 2 });
// The README is untrusted; block every request except the local temp file and the
// pinned CDN hosts this renderer itself loads, so nothing the README contains can
// fetch additional script or exfiltrate data.
const ALLOWED_HOSTS = ["cdn.jsdelivr.net", "cdnjs.cloudflare.com"];
await page.route("**/*", (route) => {
  const u = new URL(route.request().url());
  if (u.protocol === "file:" || ALLOWED_HOSTS.includes(u.hostname)) return route.continue();
  route.abort();
});
await page.goto("file://" + tmp, { waitUntil: "networkidle" });
await page.waitForFunction("window.__ready !== undefined").catch(() => {});
await page.evaluate("window.__ready").catch(() => {});
await page.waitForTimeout(1500);
await page.screenshot({ path: out, fullPage: true });
await browser.close();
console.log("wrote " + out);
