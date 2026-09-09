# Module 2 – Web Scraping: Grad Cafe Admissions Data

**Name:** Pammi (JHED ID: `gemefie1`)
**Module:** Module 2 – Web Scraping Assignment
**Due:** `September 13th 2026`

## Contents of `module_2/`

| Path | Purpose |
|---|---|
| `scrape.py` | `GradCafeScraper` class – URL management (urllib), page rendering (Selenium attached to a user-opened Chrome), parsing (BeautifulSoup / string methods / regex), resumable JSON persistence (`scrape_data`, `save_data`, `load_data`). |
| `clean.py` | `clean_data()` field-level cleaning, plus `standardize_with_llm()` which drives the instructor's local-LLM standardizer in parallel and writes `llm_extend_applicant_data.json`. |
| `applicant_data.json` | Raw-but-structured scrape output (50,000 entries, 2,500 pages). |
| `cleaned_applicant_data.json` | Output of `clean_data()` (same rows, normalized values). |
| `llm_extend_applicant_data.json` | Cleaned rows + `llm-generated-program` / `llm-generated-university`. |
| `llm_hosting/` | Instructor-provided TinyLlama standardizer (with the small edits listed below). |
| `screenshot.jpg`, `robots.txt` | Evidence of the robots.txt check (screenshot taken by the scraper itself, plus the text it evaluated). |
| `requirements.txt` | Scraper/cleaner dependencies (`llm_hosting/requirements.txt` covers the LLM step). |
| `scrape_checkpoint.json` | Resume state for the scraper (next-page cursor). |

## robots.txt compliance

`https://www.thegradcafe.com/robots.txt` was checked **before** any survey page was requested, in two ways:

1. Manually in a browser (captured as `screenshot.jpg`).
2. Programmatically: `GradCafeScraper.check_robots()` loads robots.txt in the browser, feeds the text to `urllib.robotparser.RobotFileParser`, asks `can_fetch("*", "https://www.thegradcafe.com/survey/?page=1")`, saves the screenshot and refuses to continue if the answer is "no". `python scrape.py` runs this check automatically unless `--skip-robots` is passed (used only on resumes, after the check has already passed).

The file (September 2026) contains a Cloudflare-managed block: `User-agent: *` → `Allow: /` (with a `Content-Signal: search=yes, ai-train=no, use=reference` line), followed by `Disallow: /` entries for named AI crawlers only (GPTBot, ClaudeBot, CCBot, Bytespider, Amazonbot, Applebot-Extended, Google-Extended, meta-externalagent, CloudflareBrowserRenderingCrawler). Our scraper is none of those agents, it only reads the public `/survey/` listing that is allowed for `*`, and the data is used for a course analysis exercise, not for training a model – so the scrape is within what robots.txt permits.

Polite behaviour: one page at a time, a 2-second pause between pages (`--delay`), no parallel requests, and the scraper **stops** (rather than retrying) when the site returns no results, shows a block page, or offers no further "Next" link. It never attempts to solve or bypass the Cloudflare human check – that is done once, by hand, by the person running it (see below).

## Approach

### Why a hybrid urllib + Selenium + BeautifulSoup workflow

Plain `urllib.request` calls to Grad Cafe are answered with HTTP 403 by Cloudflare, and a Selenium-launched browser is trapped in an endless "verify you are human" loop. Following the instructor's note, the scraper therefore does **not** launch a browser. Instead:

1. The user starts a normal Google Chrome with the DevTools port open (`--remote-debugging-port=9222`) and a separate profile, opens `https://www.thegradcafe.com/survey/` and clicks Cloudflare's checkbox once.
2. `scrape.py` attaches Selenium to that running window via `Options.add_experimental_option("debuggerAddress", "127.0.0.1:9222")` (Selenium Manager supplies the matching ChromeDriver automatically – no driver download or path to configure).
3. For each page it calls `driver.get(url)`, then an **explicit wait** (`WebDriverWait(...).until(presence_of_element_located("a[href*='/result/']"))`) until the results table is rendered. If Cloudflare re-appears, the scraper prints a message and simply keeps waiting (up to 5 minutes) for the human to clear it; it does not interact with the challenge.
4. `driver.page_source` is archived to `raw_html/page_NNNN.html` (for traceability and offline re-parsing with `--from-html`) and parsed.

### URL management (urllib)

* `build_survey_url(page, cursor=...)` assembles URLs with `urllib.parse.urlunparse` + `urlencode`.
* `inspect_url(url)` breaks any URL into scheme/host/path/query and validates that the host is `thegradcafe.com` before the browser is asked to load it.
* Grad Cafe uses **keyset pagination**: `?page=N` on its own always returns the first page; the real position is a base64 `cursor` parameter (`{"created_at": ..., "admitid": ..., "_pointsToNextItems": true}`) that only appears in the page's "Next" link. `_find_next_url()` extracts that link with BeautifulSoup, decomposes it with `urlparse`/`parse_qs`, and rebuilds the canonical URL. `inspect_cursor()` decodes the cursor for logging so a resume point is human-readable.
* `urllib.robotparser` evaluates robots.txt (above).

### Parsing (BeautifulSoup + string methods + regex)

Each applicant on the survey page spans several `<tr>` rows of one `<table>`:

* a **main row** – `td[0]` university, `td[1]` `<span>program</span> · <span>degree</span>`, `td[2]` date added, `td[3]` decision badge ("Accepted on Aug 28"), and the `<a href="/result/NNNNNN">` link that identifies the entry;
* an optional **badge row** – leaf `<div>` badges such as `Fall 2026`, `International`/`American`, `GPA 3.85`, `GRE 170`, `GRE V 150`, `GRE AW 3.00` (and a mobile-only copy of the decision, which is ignored);
* an optional **comment row** – a single `<p>` with the applicant's free-text comment.

`_parse_page()` walks the rows in order, starting a new record whenever a row contains a `/result/` link and attaching the following rows to it. `_parse_entry()` turns one group into a dictionary; `_normalize_status()` splits "Wait listed on Sep 07" into `("Wait listed", "Sep 07")` with a regex; badges are classified with small anchored regexes (`_TERM_RE`, `_GPA_RE`, `_GRE_RE`) and simple string comparisons. Screen-reader-only labels (`Total comments`) are removed before the raw listing text is captured. BeautifulSoup decodes HTML entities, so no tags or entities survive into the JSON.

### JSON structure

Every entry in `applicant_data.json` has the same keys (missing values are `""` in the raw file and `null` in the cleaned files – consistent within each file):

```json
{
  "program": "Artificial Intelligence, George Mason University",   // original text, never altered
  "raw_listing": "George Mason University Artificial Intelligence Masters Sep 07, 2026 Wait listed on Sep 07",
  "program_name": "Artificial Intelligence",
  "university": "George Mason University",
  "comments": "",
  "date_added": "Sep 07, 2026",
  "url": "https://www.thegradcafe.com/result/1020476",
  "status": "Wait listed",
  "decision_raw": "Wait listed on Sep 07",
  "decision_date": "Sep 07",
  "term": "Spring 2027",
  "US/International": "International",
  "GPA": "GPA 3.85",
  "GRE": "", "GRE V": "", "GRE AW": "",
  "Degree": "Masters"
}
```

The key names follow the instructor's `llm_hosting/sample_data.json` (`program`, `comments`, `date_added`, `url`, `status`, `term`, `US/International`, `GPA`, `GRE`, `GRE V`, `GRE AW`, `Degree`) so the standardizer works unchanged, with `program_name`, `university`, `decision_date`, `decision_raw` and `raw_listing` added for convenience and traceability.

### Resumability

After every page the full record list is re-written atomically (`save_data` writes a `.tmp` file and renames it) and `scrape_checkpoint.json` stores `pages_done`, `total_records` and `next_url` (the cursor link). Re-running `python scrape.py` loads the existing JSON, de-duplicates on the entry URL, and continues from `next_url`. Ctrl-C at any time is safe.

### Cleaning (`clean.py`)

`clean_data()` returns a new list of dictionaries with a fixed key order and:

* HTML tags/entities stripped (`BeautifulSoup` + `html.unescape`) and whitespace collapsed in every text field;
* `status` normalized to one of `Accepted / Rejected / Wait listed / Interview / Other`, with the date moved to `decision_date`;
* `GPA`, `GRE`, `GRE V`, `GRE AW` reduced to the bare value (`"GPA 3.85"` → `"3.85"`);
* `Degree` normalized (`PhD`, `Masters`, otherwise kept as shown: `MBA`, `MFA`, `JD`, …);
* every missing value represented as `null`;
* `program` and `raw_listing` copied through **unchanged** for reproducibility.

### Local-LLM standardization (`llm_hosting/`, driven by `clean.py --llm`)

`standardize_with_llm()` makes the 30k-row run practical:

1. Only the **unique** `program` strings are sent to the model (tens of thousands of rows collapse to a much smaller set of distinct strings).
2. The unique strings are split into *N* chunks and *N* copies of `llm_hosting/app.py --file chunk.json --out chunk.jsonl` run as separate processes (`--workers`, default = half the CPU cores; each process holds its own TinyLlama instance, ≈ 1 GB RAM).
3. Finished chunks are skipped on a rerun, so an interrupted LLM pass also resumes.
4. The JSONL results are mapped back onto every cleaned row and written as `llm_extend_applicant_data.json` with the two extra columns `llm-generated-program` and `llm-generated-university`; the original `program` field is untouched.

#### Edits made to the provided `llm_hosting/app.py`

All edits are marked with a `module_2 edit` comment in the file. None of them touch the prompt, the few-shots or the model settings.

* `hf_hub_download(...)`: removed the `local_dir_use_symlinks` and `force_filename` arguments (dropped from `huggingface_hub` ≥ 0.26, they raise `TypeError`); the model is cached in `llm_hosting/models/` relative to the script.
* `canon_universities.txt` / `canon_programs.txt` are resolved relative to `app.py` rather than the current working directory, so `clean.py` can launch it from the parent folder.
* `_fix_title_case()` replaces bare `str.title()` so connector words stay lower-case (`"Master Of Arts In Teaching"` → `"Master of Arts in Teaching"`); used for both programs and universities.
* `_post_normalize_university()`: (a) a trailing parenthetical is stripped before canonical lookup (`"Washington University in St. Louis (WashU/WUSTL)"`); (b) the difflib cutoff was raised from 0.86 to 0.90; (c) a new `_plausible_match()` guard rejects a fuzzy match unless every distinguishing word of the input has a close counterpart in the candidate. Without (b)+(c) difflib mapped `University of Michigan` → `University of Milan` (ratio 0.878), `Penn State University` → `Kent State University` (0.905), `University of Maryland` → `University of Mary` (0.90) and `University of North Carolina` → `University of South Carolina`.
* `COMMON_UNI_FIXES` gained the most frequent Grad Cafe short forms: `Penn State`, `UNC`, `UNC Chapel Hill`, `UCLA`, `UCSD`, `UC Berkeley/Davis/Irvine/San Diego`, `UT Austin`, `NYU`, `MIT`, `CMU`, `WashU`, `WUSTL`. (The fixes are applied *after* title-casing so the keys match.)

#### Canonical list changes

`canon_universities.txt` (was 1,060 lines with ~80 case-insensitive duplicates; now 985 unique lines):

* De-duplicated case-insensitively and given a trailing newline (the original file had none, so an appended entry silently merged with the last line — `"Concord UniversityUniversity of Michigan"`).
* Added: University of Michigan; University of Maryland; University of North Carolina; University of Minnesota; University of Washington; University of Illinois Chicago; University of Wisconsin–Madison; University of Colorado Boulder; University of Maryland, College Park; Ohio State University; Pennsylvania State University; Georgia Institute of Technology; University of Pittsburgh; Johns Hopkins University; Woods Hole Oceanographic Institution; University of Texas Health Science Center. These are all among the most frequent names in the scraped data that had no exact canonical entry (only a campus-qualified variant such as "University of Michigan, Ann Arbor"), which is what pushed them into the fuzzy matcher.

`canon_programs.txt`: unchanged.

#### Post-processing added in `clean.py` (`_refine_standardized`)

Grad Cafe's current page layout already shows the university in its own column, so the scraped `university` field is a more trustworthy starting point than the LLM's split of the combined `program` string. After the LLM pass, each row's scraped university is run through the (updated) `_post_normalize_university()`; when that lands **exactly** on a canonical name it replaces the LLM's answer, otherwise the LLM's answer is kept. Both standardized fields also get the connector-word fix. This corrected 1,900 university values and 5,200 program values in the 50,000-row output without re-running the model (the per-string LLM answers are cached in `llm_work/*.jsonl`, so `python clean.py --llm` re-applies the post-processing in seconds).

#### Systematic edge cases observed (50,000 rows, 17,325 unique program strings)

* **Fuzzy matching to the wrong institution** was the biggest systematic error (≈ 1,100 rows): any frequent name that was missing from the canon list but close in spelling to another canon entry got silently re-labelled (Michigan → Milan, Penn State → Kent State, Maryland → Mary). Fixed via the canon additions and the plausibility guard above; the remaining known cases are single rows (`University of Guilan` and the truncated `University of Michi` still map to `University of Milan`).
* **LLM hallucinations**: TinyLlama occasionally invents a university (`Princeton University` → `University of Prince-Tonon`, 8 rows) or returns the abbreviation as the name (`Washu/Wustl`, 29 rows). Caught by the scraped-field cross-check.
* **Campus variants remain separate**: `University of Michigan` (547) and `University of Michigan, Ann Arbor` (661) are both canonical and are kept distinct because the applicants wrote them differently; merging them is an analysis decision, not a cleaning one. Likewise `Medical University of South Carolina` (31 rows) is fuzzy-mapped to `University of South Carolina`.
* **Title-Case artefacts** from `str.title()`: connector words (`Of`, `And`, `In`, `At`) and acronyms in parentheses (`(Saic)`, `(Upf)`) — the former is fixed, the latter is not.
* **Program strings that include the degree** (`"PhD Economics"`, `"Masters in Data Science"`) — 92 rows still carry a degree word in `llm-generated-program`; the separate `Degree` field is the reliable source.
* **Non-English institutions** (e.g. `Friedrich-Schiller Universität Jena`, `Universitat Pompeu Fabra`) are not in the canon list and pass through title-cased; ~1,700 distinct university strings (≈ 6,100 rows) are still not canonical.
* `Unknown` university: 2 rows after post-processing (7 before).
* Missing values are simply absent on the site, not parse failures: comments 52 %, GPA 41 %, GRE 92 %, GRE V 94 %, GRE AW 94 %, nationality 2.4 %; `term`, `status`, `decision_date`, `url` are present on every row.

## Setup and run instructions

Tested with Python 3.10+ on macOS (Apple Silicon) with Google Chrome.

```bash
cd module_2
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 1. Start Chrome with remote debugging and pass the human check once

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
    --remote-debugging-port=9222 --user-data-dir="$HOME/chrome-gradcafe" &
```
(Linux: `google-chrome --remote-debugging-port=9222 --user-data-dir=$HOME/chrome-gradcafe &`; Windows: `"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir=%USERPROFILE%\chrome-gradcafe`.)

In that window open `https://www.thegradcafe.com/survey/` and click "Verify you are human". Leave the window open.

### 2. Scrape

```bash
python scrape.py                  # checks robots.txt (writes screenshot.jpg), then scrapes until 30,000 entries
python scrape.py --max-pages 3    # smoke test
python scrape.py --skip-robots    # resume an interrupted run
python scrape.py --from-html raw_html   # offline: rebuild applicant_data.json from archived pages
```

Progress is printed per page (`page 37: +20 (total 740) in 2.3s`). Options: `--target`, `--delay`, `--debugger`, `--output`, `--checkpoint`, `--html-dir/--no-html`, `--start-url`.

### 3. Clean and standardize

```bash
python clean.py                       # -> cleaned_applicant_data.json
pip install -r llm_hosting/requirements.txt
python clean.py --llm --workers 4     # -> llm_extend_applicant_data.json (first run downloads the ~670 MB GGUF model)
```

`llm_hosting/app.py` can still be used exactly as provided (`cd llm_hosting && python app.py --file ../cleaned_applicant_data.json --out out.jsonl`); `clean.py --llm` is only a parallel, resumable driver around it.

## Known bugs / limitations

* The scraper depends on a human completing Cloudflare's check in the attached Chrome window; if the check re-appears while nobody is watching, the run pauses for up to 5 minutes and then stops (by design – rerun to resume).
* `decision_date` is stored as shown on the site (`"Sep 07"`, no year). The year can be inferred from `date_added` in later analysis; it is not guessed here to avoid altering applicant-provided data.
* Multi-comment entries are joined into a single `comments` string.
