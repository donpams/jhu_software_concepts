"""
scrape.py - Grad Cafe admissions-results scraper (JHU Software Concepts, Module 2).

Workflow (hybrid urllib + Selenium + BeautifulSoup):

    1. urllib builds / inspects every Grad Cafe URL (urllib.parse) and evaluates
       robots.txt (urllib.robotparser).
    2. A *normal* Google Chrome window that the user opened themselves (with
       remote debugging enabled) renders the pages.  Selenium merely attaches to
       that window through the DevTools "debuggerAddress" option.  Cloudflare's
       human-verification step is completed by the user, once, by hand - the
       scraper simply waits for the results table to appear and never tries to
       evade the check.
    3. The rendered HTML (driver.page_source) is parsed with BeautifulSoup,
       Python string methods and a little regex into one dictionary per
       applicant entry.
    4. Records are appended to applicant_data.json after every page and the
       site's "Next" link (a keyset ``cursor``) is written to a small
       checkpoint file, so an interrupted run resumes where it left off.

Run ``python scrape.py --help`` for the CLI, or see README.md.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import sys
import time
import urllib.robotparser
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup, Tag

# --------------------------------------------------------------------------- #
# URL management (urllib)                                                     #
# --------------------------------------------------------------------------- #
BASE_URL = "https://www.thegradcafe.com"
SURVEY_PATH = "/survey/"
ROBOTS_URL = urljoin(BASE_URL, "/robots.txt")
USER_AGENT = "*"  # the robots.txt group our (non-AI-crawler) scraper falls under

DEFAULT_OUTPUT = Path("applicant_data.json")
DEFAULT_CHECKPOINT = Path("scrape_checkpoint.json")
DEFAULT_HTML_DIR = Path("raw_html")

# Text Cloudflare shows while it is deciding whether we are human.
CLOUDFLARE_MARKERS = ("Just a moment...", "Verify you are human", "cf-chl")


def build_survey_url(page: int, **extra_query: Any) -> str:
    """Return the canonical URL for one page of Grad Cafe survey results.

    The URL is assembled with urllib.parse so that query encoding is always
    correct (e.g. ``https://www.thegradcafe.com/survey/?page=3``).
    """
    if page < 1:
        raise ValueError("page numbers start at 1")
    query = {"page": page, **extra_query}
    parts = urlparse(BASE_URL)
    return urlunparse(
        (parts.scheme, parts.netloc, SURVEY_PATH, "", urlencode(query), "")
    )


def inspect_cursor(url: str) -> Optional[Dict[str, Any]]:
    """Decode the base64 ``cursor`` query parameter Grad Cafe uses for paging.

    Grad Cafe ignores ``page=N`` on its own; the real position is a keyset
    cursor such as ``{"created_at": "...", "admitid": 1020459, ...}``.  We
    decode it purely for logging / traceability, never to fabricate one.
    """
    cursor = parse_qs(urlparse(url).query).get("cursor", [None])[0]
    if not cursor:
        return None
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        return json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {"raw": cursor}


def inspect_url(url: str) -> Dict[str, Any]:
    """Break a Grad Cafe URL into its components (used for validation/logging)."""
    parts = urlparse(url)
    query = {k: v[0] if len(v) == 1 else v for k, v in parse_qs(parts.query).items()}
    return {
        "scheme": parts.scheme,
        "host": parts.netloc,
        "path": parts.path,
        "query": query,
        "page": int(query["page"]) if str(query.get("page", "")).isdigit() else None,
        "is_gradcafe": parts.netloc.endswith("thegradcafe.com"),
        "cursor": inspect_cursor(url),
    }


def result_url_from_href(href: str) -> str:
    """Turn a relative ``/result/123456`` link into an absolute URL."""
    return urljoin(BASE_URL, href)


# --------------------------------------------------------------------------- #
# JSON persistence                                                            #
# --------------------------------------------------------------------------- #
def save_data(records: List[Dict[str, Any]], path: Path | str = DEFAULT_OUTPUT) -> None:
    """Write the list of applicant dictionaries to ``path`` as UTF-8 JSON."""
    path = Path(path)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(records, fh, ensure_ascii=False, indent=2)
    tmp_path.replace(path)  # atomic on POSIX -> a crash never leaves a half file


def load_data(path: Path | str = DEFAULT_OUTPUT) -> List[Dict[str, Any]]:
    """Load previously saved applicant dictionaries (empty list if none)."""
    path = Path(path)
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    return data if isinstance(data, list) else data.get("rows", [])


# --------------------------------------------------------------------------- #
# HTML parsing helpers                                                        #
# --------------------------------------------------------------------------- #
_WS_RE = re.compile(r"\s+")
_DECISION_RE = re.compile(
    r"^(?P<status>Accepted|Rejected|Wait ?listed|Interview|Other)"
    r"(?:\s+on\s+(?P<date>.+))?$",
    re.IGNORECASE,
)
_TERM_RE = re.compile(r"^(Fall|Spring|Summer|Winter)\s+\d{4}$", re.IGNORECASE)
_GPA_RE = re.compile(r"^GPA\s+(?P<value>[\d.]+)$", re.IGNORECASE)
_GRE_RE = re.compile(r"^GRE\s+(?P<kind>V|AW|Q)?\s*(?P<value>[\d.]+)$", re.IGNORECASE)
_DEGREE_WORDS = ("PhD", "Masters", "MBA", "MFA", "JD", "EdD", "PsyD", "Other")


def _clean_text(value: Optional[str]) -> str:
    """Collapse whitespace and strip; HTML entities are already decoded by bs4."""
    return _WS_RE.sub(" ", value or "").strip()


def _text(node: Optional[Tag]) -> str:
    return _clean_text(node.get_text(" ", strip=True)) if node else ""


class GradCafeScraper:
    """Scrape, parse and persist Grad Cafe admissions results.

    Parameters
    ----------
    delay_seconds:
        Polite pause between page loads (SHOULD requirement).
    debugger_address:
        ``host:port`` of a Chrome instance started with
        ``--remote-debugging-port``.  Selenium attaches to it instead of
        launching its own browser, which is what lets a human clear the
        Cloudflare check once.
    html_dir:
        If given, every rendered page is saved here (page_0001.html ...) for
        traceability / offline re-parsing.
    """

    def __init__(
        self,
        delay_seconds: float = 2.0,
        debugger_address: str = "127.0.0.1:9222",
        html_dir: Optional[Path] = DEFAULT_HTML_DIR,
        challenge_timeout: int = 300,
    ) -> None:
        self.delay_seconds = delay_seconds
        self.debugger_address = debugger_address
        self.html_dir = Path(html_dir) if html_dir else None
        self.challenge_timeout = challenge_timeout
        self._driver = None  # created lazily (Selenium import is optional for parsing)

    # ------------------------------------------------------------------ #
    # Browser plumbing (Selenium)                                         #
    # ------------------------------------------------------------------ #
    @property
    def driver(self):
        """Attach to the user's already-running Chrome on first use."""
        if self._driver is None:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options

            options = Options()
            options.add_experimental_option("debuggerAddress", self.debugger_address)
            # Selenium Manager (bundled with selenium>=4.6) resolves chromedriver.
            self._driver = webdriver.Chrome(options=options)
        return self._driver

    def _wait_for_results(self, timeout: int) -> bool:
        """Explicit wait until the results table is rendered.

        Returns True when at least one ``/result/`` link is present, False on
        timeout.  While Cloudflare's challenge is showing we keep waiting so
        the user can complete it by hand; nothing here interacts with it.
        """
        from selenium.common.exceptions import TimeoutException
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait

        try:
            WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "a[href*='/result/']"))
            )
            return True
        except TimeoutException:
            return False

    def _fetch_page_html(self, url: str, page: int) -> str:
        """Load one survey page (by URL) in the attached Chrome, return its HTML.

        ``page`` is only used to name the archived HTML file.
        """
        info = inspect_url(url)
        if not info["is_gradcafe"]:
            raise ValueError(f"refusing to load non-GradCafe URL {url}")

        self.driver.get(url)
        if not self._wait_for_results(timeout=15):
            # Probably the Cloudflare interstitial.  Ask the user to clear it
            # and wait patiently - but never attempt to solve it ourselves.
            if self._looks_blocked(self.driver.page_source):
                print(
                    f"\n[!] Cloudflare verification is showing for {url}.\n"
                    f"    Please complete it in the Chrome window (waiting up to "
                    f"{self.challenge_timeout}s)...",
                    file=sys.stderr,
                )
                if not self._wait_for_results(timeout=self.challenge_timeout):
                    raise RuntimeError("Site did not return results; stopping (blocked?)")
            else:
                raise RuntimeError(f"No results table found on {url}")

        html = self.driver.page_source
        if self.html_dir is not None:
            self.html_dir.mkdir(parents=True, exist_ok=True)
            (self.html_dir / f"page_{page:04d}.html").write_text(html, encoding="utf-8")
        return html

    @staticmethod
    def _looks_blocked(html: str) -> bool:
        """Heuristic: is this a Cloudflare challenge / block page?"""
        head = html[:20000]
        return any(marker in head for marker in CLOUDFLARE_MARKERS) or "403 Forbidden" in head

    # ------------------------------------------------------------------ #
    # robots.txt                                                          #
    # ------------------------------------------------------------------ #
    def check_robots(self, screenshot_path: Optional[Path] = Path("screenshot.jpg")) -> bool:
        """Load robots.txt in the browser, evaluate it with urllib.robotparser.

        The rendered page is screenshotted as evidence (screenshot.jpg) and the
        verdict for the survey URL is returned.  Scraping is refused if the
        survey path is disallowed for our user-agent group.
        """
        self.driver.get(ROBOTS_URL)
        time.sleep(1.5)
        body = self.driver.find_element("tag name", "body").text
        if self._looks_blocked(body):
            print("[!] robots.txt is behind the Cloudflare check; complete it, then rerun.")
            return False

        parser = urllib.robotparser.RobotFileParser(ROBOTS_URL)
        parser.parse(body.splitlines())
        allowed = parser.can_fetch(USER_AGENT, build_survey_url(1))
        print(f"robots.txt: {'ALLOWS' if allowed else 'DISALLOWS'} {SURVEY_PATH} for User-agent {USER_AGENT!r}")

        if screenshot_path:
            self.driver.save_screenshot(str(Path(screenshot_path).with_suffix(".png")))
            try:  # convert to .jpg as the assignment asks (Pillow ships with selenium deps)
                from PIL import Image

                img = Image.open(Path(screenshot_path).with_suffix(".png")).convert("RGB")
                img.save(screenshot_path, "JPEG", quality=90)
                Path(screenshot_path).with_suffix(".png").unlink()
            except ImportError:
                pass
            Path("robots.txt").write_text(body, encoding="utf-8")
        return allowed

    # ------------------------------------------------------------------ #
    # Parsing (BeautifulSoup + string methods + regex)                   #
    # ------------------------------------------------------------------ #
    def _parse_page(self, html: str) -> List[Dict[str, Any]]:
        """Return a list of applicant dictionaries found in one page's HTML.

        Each applicant on Grad Cafe spans one *main* table row (university,
        program, date added, decision, link) followed by zero or more
        *detail* rows (term / nationality / GPA / GRE badges, and the free-text
        comment).  We walk the rows in order and group them.
        """
        soup = BeautifulSoup(html, "html.parser")
        table = soup.find("table")
        if table is None:
            return []

        records: List[Dict[str, Any]] = []
        main_row: Optional[Tag] = None
        detail_rows: List[Tag] = []

        for row in table.find_all("tr"):
            if row.find("a", href=re.compile(r"/result/\d+")):
                if main_row is not None:
                    records.append(self._parse_entry(main_row, detail_rows))
                main_row, detail_rows = row, []
            elif main_row is not None:
                detail_rows.append(row)
        if main_row is not None:
            records.append(self._parse_entry(main_row, detail_rows))
        return records

    @staticmethod
    def _find_next_url(html: str) -> Optional[str]:
        """Return the absolute URL of the "Next" pagination link, if any.

        Grad Cafe pages with a keyset ``cursor`` parameter, so the only
        reliable way to reach page N+1 is to follow the link the site gives
        us.  The href is normalised with urllib (parse -> rebuild) so the
        request always goes to the canonical survey path.
        """
        soup = BeautifulSoup(html, "html.parser")
        for anchor in soup.find_all("a", href=True):
            if _text(anchor).lower() == "next":
                href = urljoin(BASE_URL, anchor["href"])
                query = parse_qs(urlparse(href).query)
                cursor = query.get("cursor", [None])[0]
                page = query.get("page", ["1"])[0]
                if not cursor:
                    return None
                return build_survey_url(int(page) if page.isdigit() else 1, cursor=cursor)
        return None

    def _parse_entry(self, main_row: Tag, detail_rows: Iterable[Tag]) -> Dict[str, Any]:
        """Convert one applicant's table rows into a flat dictionary."""
        # Drop screen-reader-only labels ("Total comments") so they do not
        # pollute the preserved raw listing text.
        for hidden in main_row.select(".tw-sr-only"):
            hidden.decompose()
        cells = main_row.find_all("td")
        university = _text(cells[0]) if len(cells) > 0 else ""

        # Program cell: "<span>Program</span> ... <span>Degree</span>"
        program_cell = cells[1] if len(cells) > 1 else None
        spans = [_text(s) for s in program_cell.find_all("span")] if program_cell else []
        spans = [s for s in spans if s]
        program_name = spans[0] if spans else _text(program_cell)
        degree = next((s for s in spans[1:] if s in _DEGREE_WORDS), "")
        if not degree:
            degree = next((s for s in spans[1:]), "")

        date_added = _text(cells[2]) if len(cells) > 2 else ""
        decision_raw = _text(cells[3]) if len(cells) > 3 else ""
        status, decision_date = self._normalize_status(decision_raw)

        link = main_row.find("a", href=re.compile(r"/result/\d+"))
        entry_url = result_url_from_href(link["href"]) if link else ""

        # Badges and comment from the detail rows
        term = nationality = gpa = gre = gre_v = gre_aw = ""
        comments: List[str] = []
        for row in detail_rows:
            paragraph = row.find("p")
            if paragraph is not None:
                comments.append(_text(paragraph))
                continue
            for badge in row.find_all("div"):
                if badge.find("div"):
                    continue  # only leaf <div>s are badges
                text = _text(badge)
                if not text:
                    continue
                if _TERM_RE.match(text):
                    term = text
                elif text in ("International", "American"):
                    nationality = text
                elif _GPA_RE.match(text):
                    gpa = text
                elif (m := _GRE_RE.match(text)):
                    kind = (m.group("kind") or "").upper()
                    if kind == "V":
                        gre_v = text
                    elif kind == "AW":
                        gre_aw = text
                    elif kind == "":
                        gre = text

        return {
            # raw text preserved for traceability
            "program": f"{program_name}, {university}",
            "raw_listing": _text(main_row),
            # cleaned / split fields
            "program_name": program_name,
            "university": university,
            "comments": " ".join(comments),
            "date_added": date_added,
            "url": entry_url,
            "status": status,
            "decision_raw": decision_raw,
            "decision_date": decision_date,
            "term": term,
            "US/International": nationality,
            "GPA": gpa,
            "GRE": gre,
            "GRE V": gre_v,
            "GRE AW": gre_aw,
            "Degree": degree,
        }

    @staticmethod
    def _normalize_status(decision_text: str) -> tuple[str, str]:
        """Split 'Accepted on 15 Mar' into ('Accepted', '15 Mar')."""
        match = _DECISION_RE.match(decision_text)
        if not match:
            return decision_text, ""
        status = match.group("status")
        status = "Wait listed" if status.lower().replace(" ", "") == "waitlisted" else status.capitalize()
        return status, _clean_text(match.group("date"))

    # ------------------------------------------------------------------ #
    # Orchestration                                                       #
    # ------------------------------------------------------------------ #
    def scrape_data(
        self,
        target_rows: int = 30000,
        start_url: Optional[str] = None,
        max_pages: Optional[int] = None,
        output: Path = DEFAULT_OUTPUT,
        checkpoint: Path = DEFAULT_CHECKPOINT,
    ) -> List[Dict[str, Any]]:
        """Pull pages until ``target_rows`` entries are stored (resumable).

        Existing records in ``output`` are loaded first.  The run continues
        from the ``next_url`` stored in the checkpoint (the cursor link the
        site handed us after the last completed page), or from ``start_url``
        / page 1 when there is no checkpoint.  Duplicate entry URLs are
        skipped.  Scraping stops as soon as the site blocks or rate-limits us,
        returns an empty page, or offers no further "Next" link.
        """
        records = load_data(output)
        seen_urls = {r["url"] for r in records if r.get("url")}
        state = self._read_checkpoint(checkpoint)
        page = int(state.get("pages_done", 0)) + 1
        url = start_url or state.get("next_url") or build_survey_url(1)
        pages_done = 0
        print(f"Resuming with {len(records)} records at page {page}: {inspect_url(url)['cursor'] or 'first page'}")

        while len(records) < target_rows and (max_pages is None or pages_done < max_pages):
            started = time.time()
            try:
                html = self._fetch_page_html(url, page)
            except RuntimeError as exc:
                print(f"[stop] {exc}", file=sys.stderr)
                break

            page_records = self._parse_page(html)
            if not page_records:
                print(f"[stop] page {page} contained no entries", file=sys.stderr)
                break

            new = [r for r in page_records if r["url"] not in seen_urls]
            seen_urls.update(r["url"] for r in new)
            records.extend(new)
            next_url = self._find_next_url(html)

            save_data(records, output)
            self._write_checkpoint(checkpoint, pages_done=page, next_url=next_url, total=len(records))
            pages_done += 1
            print(f"page {page:5d}: +{len(new):3d} (total {len(records)}) in {time.time() - started:.1f}s")

            if next_url is None:
                print("[stop] no further pages", file=sys.stderr)
                break
            url = next_url
            page += 1
            time.sleep(self.delay_seconds)  # polite throttling

        return records

    def parse_saved_html(self, html_dir: Path, output: Path = DEFAULT_OUTPUT) -> List[Dict[str, Any]]:
        """Offline mode: rebuild applicant_data.json from previously saved pages."""
        records: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for path in sorted(Path(html_dir).glob("page_*.html")):
            for rec in self._parse_page(path.read_text(encoding="utf-8")):
                if rec["url"] not in seen:
                    seen.add(rec["url"])
                    records.append(rec)
        save_data(records, output)
        print(f"parsed {len(records)} records from {html_dir}")
        return records

    @staticmethod
    def _read_checkpoint(path: Path) -> Dict[str, Any]:
        """Return the saved progress dict ({} when no checkpoint exists)."""
        try:
            return json.loads(Path(path).read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            return {}

    @staticmethod
    def _write_checkpoint(path: Path, pages_done: int, next_url: Optional[str], total: int) -> None:
        Path(path).write_text(
            json.dumps({"pages_done": pages_done, "next_url": next_url, "total_records": total,
                        "saved_at": time.ctime()}, indent=2),
            encoding="utf-8",
        )

    def close(self) -> None:
        """Detach from Chrome (the user's window stays open)."""
        if self._driver is not None:
            try:
                self._driver.quit()
            finally:
                self._driver = None


# --------------------------------------------------------------------------- #
# CLI                                                                         #
# --------------------------------------------------------------------------- #
def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--target", type=int, default=30000, help="stop once this many entries are saved")
    parser.add_argument("--start-url", default=None, help="survey URL (with cursor) to start from; overrides the checkpoint")
    parser.add_argument("--max-pages", type=int, default=None, help="load at most this many pages this run")
    parser.add_argument("--delay", type=float, default=2.0, help="seconds to wait between pages")
    parser.add_argument("--debugger", default="127.0.0.1:9222", help="Chrome remote-debugging address")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--html-dir", type=Path, default=DEFAULT_HTML_DIR, help="where rendered pages are archived")
    parser.add_argument("--no-html", action="store_true", help="do not archive rendered HTML")
    parser.add_argument("--skip-robots", action="store_true", help="skip the robots.txt check (already verified)")
    parser.add_argument("--from-html", type=Path, default=None, help="offline: parse saved pages instead of scraping")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    scraper = GradCafeScraper(
        delay_seconds=args.delay,
        debugger_address=args.debugger,
        html_dir=None if args.no_html else args.html_dir,
    )
    try:
        if args.from_html:
            scraper.parse_saved_html(args.from_html, args.output)
            return 0
        if not args.skip_robots and not scraper.check_robots():
            print("robots.txt does not permit scraping the survey pages - aborting.")
            return 1
        scraper.scrape_data(
            target_rows=args.target,
            start_url=args.start_url,
            max_pages=args.max_pages,
            output=args.output,
            checkpoint=args.checkpoint,
        )
    finally:
        scraper.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
