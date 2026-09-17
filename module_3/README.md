# Module 3 – Database Queries, SQLAlchemy, and a Dynamic Webpage

**Name:** Pammi (JHED ID: `gemefie1`)
**Module:** Module 3 – Database Queries, SQLAlchemy, and Dynamic Webpages
**Repository:** see `github.txt`

## Contents

| Path | Purpose |
|---|---|
| `load_data.py` | Creates the `applicants` table and loads Module 2's `data/llm_extend_applicant_data.json` with **psycopg 3**. Idempotent (`ON CONFLICT DO NOTHING`). |
| `query_data.py` | Questions 1–9 plus two original questions (10, 11) answered in **raw SQL** through psycopg; prints formatted results. |
| `models.py` | SQLAlchemy 2.x `Applicant` model mapped to the existing table, plus `engine`, `SessionLocal`, `get_session()`. |
| `orm_queries.py` | Questions 1, 4, 5, 8, 9 and original question 10 (and the rest, for the webpage) written with `select()` / `func` / `and_` / `or_` – no raw SQL. |
| `app.py`, `templates/index.html`, `static/style.css` | Flask analysis page with **Pull Data** and **Update Analysis** buttons; all reads go through the ORM. |
| `pull_new_data.py` | Pipeline behind Pull Data: Module 2 scraper → clean → standardize → insert. Runs as a subprocess. |
| `scrape.py`, `clean.py`, `llm_hosting/` | Module 2 scraping/cleaning code reused by Pull Data (`scrape.py` gained `scrape_new_entries()`). |
| `config.py`, `.env.example` | `DATABASE_URL` handling; real credentials live only in a git-ignored `.env`. |
| `query_results.pdf`, `make_query_results_pdf.py` | Part 4 PDF (question, result, SQL, explanation for all 11 questions) and the script that builds it from live results. |
| `limitations.pdf`, `make_limitations_pdf.py` | Part 11 reflection. |
| `screenshots/` | SQL console output, ORM console output, running webpage. |
| `data/llm_extend_applicant_data.json` | Module 2 output (50,000 cleaned + LLM-standardized rows) that seeds the database. |
| `requirements.txt`, `github.txt` | Dependencies; SSH URL of the private repo. |

## Setup

Tested with Python 3.12 and PostgreSQL 16 on macOS (Homebrew) and Linux.

### 1. PostgreSQL

```bash
brew install postgresql@16
brew services start postgresql@16
createdb gradcafe
```

(Postgres.app users: open the app, click *Initialize*, then `createdb gradcafe`. Docker: `docker run -d --name gradcafe -e POSTGRES_PASSWORD=postgres -p 5432:5432 postgres:16` then `docker exec gradcafe createdb -U postgres gradcafe`.)

### 2. Python environment and credentials

```bash
cd module_3
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # edit if your DB needs a user/password or another port
```

`config.py` reads `DATABASE_URL` from the environment (or `.env`), e.g. `postgresql://localhost:5432/gradcafe` or `postgresql://user:pass@host:5432/gradcafe`. `.env` is git-ignored; no secrets are committed.

### 3. Load the data (Part 1)

```bash
python load_data.py
# llm_extend_applicant_data.json: 50000 records read, 50000 inserted, 0 skipped ...; table now holds 50000 rows
python load_data.py             # second run: 0 inserted, 50000 skipped -> no duplicates
```

### 4. Run the analyses (Parts 2, 3, 6)

```bash
python query_data.py            # raw SQL through psycopg
python orm_queries.py           # SQLAlchemy ORM
python make_query_results_pdf.py   # regenerates query_results.pdf from the live database
python make_limitations_pdf.py     # regenerates limitations.pdf
```

### 5. Web app (Parts 8–10)

```bash
python app.py                   # http://127.0.0.1:5000
```

For **Pull Data** the Module 2 scraper needs the same Chrome-with-remote-debugging window as before (Cloudflare blocks plain requests and headless browsers, and the human check must be completed by a person):

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --remote-debugging-port=9222 --user-data-dir="$HOME/chrome-gradcafe" &
```

Open `https://www.thegradcafe.com/survey/` in that window and clear the "Verify you are human" box once. Pull Data can also be run by hand: `python pull_new_data.py [--no-llm] [--max-pages N]`.

## Design notes

### Table and loader

* Schema exactly as specified (`p_id integer PK, program, comments, date_added date, url, status, term, us_or_international, gpa/gre/gre_v/gre_aw float, degree, llm_generated_program, llm_generated_university`), created with `CREATE TABLE IF NOT EXISTS`.
* **`p_id` is the numeric id in the Grad Cafe entry URL** (`/result/1020478` → `1020478`). It is unique on the site, stable across scrapes, and makes re-loading and Pull Data naturally idempotent via `ON CONFLICT (p_id) DO NOTHING`; `url` also carries a UNIQUE constraint.
* Missing values (`null`/`""`) become SQL `NULL`. Numbers are parsed defensively (`"GPA 3.85"` → 3.85, unparsable → NULL). `date_added` accepts the formats Grad Cafe has used ("Sep 08, 2026", "March 31, 2024", "Added on …"). Nothing in the loader raises on an optional field.
* Rows are inserted in batches of 1,000 with `executemany`; the whole 50k load takes ~2 s.

### Query conventions

* Text matching is case-insensitive (`ILIKE`, `~*`). "Accepted" is `status ILIKE 'accept%'`; master's is `degree ILIKE 'master%' OR 'ms' OR 'm.s.%'`; "MIT"/"JHU" use PostgreSQL word boundaries (`~* '\mMIT\M'`) so they do not match inside other words.
* Percentages use `100.0 * COUNT(*) FILTER (WHERE …) / NULLIF(COUNT(*), 0)` and are rounded to 2 decimals; counts are whole numbers.
* **"Provides the metric" means a value that is possible on that scale.** Grad Cafe's badge is labelled just "GRE", and ~60 % of the 3,769 GRE values are combined totals (260–340); placeholders such as GPA 9.99 or AW 99.99 also occur. A naive `AVG(gre)` gives 261.49. All averages therefore use `gre BETWEEN 130 AND 170`, `gre_v BETWEEN 130 AND 170`, `gre_aw BETWEEN 0 AND 6`, `gpa > 0 AND gpa <= 4.0` (each metric filtered independently, so an applicant missing one score still counts for the others). The same rule is applied in SQL, ORM and the webpage.

### Results (50,000 rows, scraped 8 Sep 2026)

| # | Question | Result |
|---|---|---|
| 1 | Fall 2026 applicant count | 33,207 |
| 2 | Percent international | 47.89% |
| 3 | Average GPA / GRE Q / GRE V / GRE AW | 3.75 / 165.75 / 160.37 / 4.33 |
| 4 | Average GPA, American, Fall 2026 | 3.79 |
| 5 | Fall 2025 acceptance percentage | 40.74% |
| 6 | Average GPA, accepted, Fall 2026 | 3.76 |
| 7 | JHU Computer Science master's entries | 20 |
| 8 | Fall 2026 CS PhD acceptances at Georgetown/MIT/Stanford/CMU (original fields) | 30 |
| 9 | Same with LLM fields | 30 (difference +0) |
| 10 | Acceptance rate by degree (≥500 entries) | PhD 24.38%, Masters 67.59%, MFA 35.59%, PsyD 36.03% |
| 11 | Top-10 universities for Fall 2026 | Stanford 769 entries (18.34%, GPA 3.85), Berkeley 728, Yale 633, … |

Q8 and Q9 select exactly the same 30 rows: Grad Cafe's current layout shows the university in its own column, so the Module 2 pipeline already stored clean university names and the LLM/canonical post-processing preserved them. The counts would diverge if applicants had typed abbreviations or misspellings the free-text search misses, or if the `MIT` regex over-matched – which is what the standardized columns protect against. The full discussion is in `query_results.pdf`.

## SQL vs. SQLAlchemy (Part 7) – Question 5

Raw SQL (`query_data.py`):

```sql
SELECT ROUND(100.0 * COUNT(*) FILTER (WHERE status ILIKE 'accept%') / NULLIF(COUNT(*), 0), 2)
FROM applicants
WHERE term ILIKE 'fall 2025';
```

SQLAlchemy (`orm_queries.py`, with the `_pct()` helper inlined):

```python
FALL_2025 = Applicant.term.ilike("fall 2025")
ACCEPTED = Applicant.status.ilike("accept%")

matched = func.count(case((ACCEPTED, 1)))
stmt = select(100.0 * matched / func.nullif(func.count(Applicant.p_id), 0)).where(FALL_2025)
value = session.scalar(stmt)
```

The ORM version composes from reusable Python expressions – `FALL_2025` and `ACCEPTED` are defined once and shared by Questions 1, 5, 6, 8 and 9 and by the Flask app, so a change to how "accepted" is recognised happens in one place, and the query builder handles quoting and parameter binding, which removes a whole class of injection and typo bugs. The raw SQL, on the other hand, is shorter, reads exactly like what PostgreSQL will execute, and lets me use PostgreSQL-specific syntax such as `COUNT(*) FILTER (WHERE …)` and `ROUND(… , 2)` directly; in SQLAlchemy I had to express the filtered count as `count(case(...))` and round in Python, and when a query misbehaves I still end up reading the generated SQL to debug it. Raw SQL is also what a DBA or a non-Python teammate can run in `psql` unchanged, while the ORM pays for its portability and composability with an extra layer of abstraction. Neither is always better: the ORM is the right tool for the application code (models, webpage), and raw SQL is the right tool for ad-hoc analysis and for squeezing the most out of one specific database.

## Web application

* `GET /` – renders `templates/index.html` with every figure fetched through `orm_queries.py` functions (which use the `Applicant` model and a `Session`), so no Flask route touches SQL or psycopg.
* `POST /pull` (**Pull Data**) – starts `pull_new_data.py` with `subprocess.Popen`. If a pull is already running (the process handle is alive, or `pull_status.json` says `running`) the request is refused with a message. The page explains what the button does and disables it while a pull is active; a small `/status` JSON endpoint is polled every 5 s to update the banner.
* `POST /update` (**Update Analysis**, top-right) – re-queries PostgreSQL and redirects to `/`. It never scrapes. If a pull is running it tells the user that new data is currently being retrieved and shows the current database contents; otherwise it confirms the refresh time.
* `pull_new_data.py` reads the URLs already in the table, runs `GradCafeScraper.scrape_new_entries()` from Grad Cafe's newest page until a page yields no unseen entry (safety cap `--max-pages`), cleans the rows with Module 2's `clean_data()`, adds the LLM columns (local TinyLlama when `llm_hosting` dependencies are installed; otherwise the scraped university/program passed through the same canonical-name post-processor), and inserts with `ON CONFLICT DO NOTHING`, so existing rows are never overwritten. Progress and errors are written to `pull_status.json` for the page.

## Known limitations

* Pull Data depends on a human-cleared Chrome session; if Cloudflare shows its check while nobody is watching, the scraper waits up to 5 minutes and then stops with an error message shown on the page (rerun after clearing it).
* The score-range rule above is a judgement call; it is documented in the PDF and reflected in `limitations.pdf`.
* Q9's four universities are matched by exact canonical names; a new spelling that the Module 2 standardizer did not map (e.g. an unknown abbreviation) would be missed there but might still be caught by Q8's free-text search.
