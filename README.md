# Rutgers What-If Major

A personal tool that pulls **your own** Degree Navigator audit and shows what
changes if you switch to, or add, another major or minor (CS, Math,
Statistics, ...). Python + Playwright + httpx. Everything runs on your
machine, and your data stays in `data/` (git-ignored).

## Ground rules this tool follows

* **You log in yourself.** `login` opens a normal browser window. You type your
  NetID and password and approve Duo. The code never fills those fields and
  never automates Duo.
* **The session is saved to `auth.json`** (file mode 600, git-ignored) and
  reused until Rutgers expires it. Then you run `login` again.
* **Only your own data.** It fetches only the Degree Navigator pages you open
  yourself during `discover`.
* **Slow.** There's a random 1–2 s pause between page loads and requests
  (`RWI_MIN_DELAY` / `RWI_MAX_DELAY`). Schedule of Classes data is downloaded
  once per term and cached.
* Follow the [Rutgers acceptable use policy](https://policies.rutgers.edu/)
  for university IT resources.

## Setup (once)

```bash
git clone https://github.com/rahulk462/Rutgers-What-If-Major.git
cd Rutgers-What-If-Major
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
playwright install chromium        # downloads the browser Playwright drives
pytest -q                          # optional: run the tests (should all pass)
```

## Run it in your browser (localhost)

```bash
python -m rutgers_whatif serve
```

This opens **http://127.0.0.1:8000** (use `--port` to change it, or `--no-browser`
to stop it opening a tab). The page walks you through the same steps as the
commands below: log in, discover, scrape (or paste a course CSV), download course
data, then compare programs. When a step opens a browser window for you (login
or discovery), do your part there, then click **I'm done** on the page. The
server only listens on 127.0.0.1 and rejects requests from any other host name.
Stop it with Ctrl+C.

## Workflow (command line)

```bash
# 1. Log in by hand (NetID + Duo) and save the session to auth.json
python -m rutgers_whatif login
python -m rutgers_whatif check-session      # later: is the session still alive?

# 2. Find out how Degree Navigator delivers its data (DevTools-style)
python -m rutgers_whatif discover
#    A browser opens. Click through your audit and course history yourself,
#    then press Enter. Every response from Rutgers is saved to
#    data/raw/discovery/. If any was JSON, scraping uses those endpoints with
#    httpx. Otherwise it parses the HTML. The result is written to data/dn_pages.json.

# 3. Pull your audit (throttled) and save it to data/audit.json + data/whatif.sqlite
python -m rutgers_whatif scrape
python -m rutgers_whatif reparse            # re-run parsing on saved pages, no network

# 4. Download public course + prerequisite data (Schedule of Classes API)
python -m rutgers_whatif soc --year 2026 --term spring --term fall
python -m rutgers_whatif soc --year 2027 --term spring

# 5. Compare programs
python -m rutgers_whatif programs           # list the defined programs
python -m rutgers_whatif whatif cs-ba math-minor stat-ba --current cs-bs
python -m rutgers_whatif whatif --current cs-bs --json > data/whatif.json
python -m rutgers_whatif prereq 01:198:344  # prereqs for one course, and whether you meet them
```

Try it without logging in, using the made-up sample transcript:

```bash
python -m rutgers_whatif whatif cs-ba math-minor --current cs-bs --courses examples/sample_courses.csv
```

### If scraping doesn't parse your pages well

Degree Navigator's markup isn't documented, so the HTML parser uses
heuristics: tables with course and grade columns, and audit blocks named like
`R1:` with a complete/incomplete status. If it misses things you can:

1. Put CSS selectors in `data/dn_selectors.json` and run `reparse`:
   ```json
   {"requirement_block": "div.requirement", "requirement_name": ".req-title", "status": "img.status"}
   ```
2. Or skip scraping: export your courses to a CSV with the columns
   `code,title,credits,grade,term` and run `python -m rutgers_whatif import-courses my_courses.csv`.
3. Or share one saved page from `data/raw/` **with your name/RUID removed**
   so the parser can be fitted to the real markup.

## What gets extracted

| Field | Where |
|---|---|
| Requirement name, satisfied or not, courses applied, credits remaining | `requirements` in `data/audit.json` / SQLite |
| Completed courses with grade, term, credits | `courses` in `data/audit.json` / SQLite |

The SQLite file keeps every scrape as a snapshot (`snapshots`, `courses`,
`requirements` tables), so you can see how the audit changes over time.

## How the what-if engine works

* Program definitions live in `rutgers_whatif/programs/*.json`, condensed from
  the department requirement pages (sources and retrieval date are in each
  file). They currently cover the CS B.S., CS B.A., CS minor, Math major
  (Option A), Math minor, Statistics major, Statistics/Math joint major, and
  Statistics minor.
* Requirement types: `all` (every listed course), `choose` (N from a list or
  wildcard like `01:640:3xx`, with rules such as "at least 2 at 300+" or "at
  most 1 independent study"), and `one_set` (finish any one sequence).
* Grade policies: CS allows one D. Math needs C or better with one exception.
  Statistics allows no D.
* `equivalents.json` maps the old CS 111/112 to the new 121/122 (the new intro
  sequence starts Spring 2027) and honors calculus to regular calculus. The
  honors-calculus mappings are marked as assumptions, so check them with an advisor.
* Output for each program: requirements met, courses left, estimated credits
  left, which of your courses already count, and which needed courses you can
  take now (prerequisites from the SOC data). With `--current`, it also shows
  the change if you **switch** and the extra courses if you **add** it.

Not modeled yet: admission-to-major rules, residency rules, the ten-year
limit for CS electives, the SAS core, and the Math honors and actuarial
tracks. Degree Navigator and your advisor are the final word.

## Layout

```
rutgers_whatif/
  auth.py          manual login, auth.json save/reuse, session check
  discover.py      record Degree Navigator network traffic (JSON vs HTML)
  scrape.py        throttled fetch (httpx for JSON, Playwright for HTML)
  dn_parse.py      HTML/JSON -> courses + requirements
  storage.py       JSON + SQLite, CSV/JSON import
  soc.py           Schedule of Classes API download + cache
  prereqs.py       parse/evaluate SOC prerequisite strings
  requirements.py  requirement model + evaluator
  whatif.py        multi-program comparison and report
  web.py, web/     local web page (`serve`)
  programs/        requirement definitions (JSON)
tests/             pytest suite with real SOC prerequisite samples
```

## Possible later additions

Semester-by-semester graduation planner, prerequisite graph, schedule
builder (would need `soc.py` to also keep sections and meeting times, which it currently drops).
