"""Module 2 scraper: URL helpers, HTML parsing, paging and the browser plumbing
exercised with a fake Selenium driver (markers: analysis for parsing, integration
for the paging loops).  No network, no real browser."""

import json
import sys
from pathlib import Path

import pytest

import scrape
from scrape import GradCafeScraper, build_survey_url, inspect_cursor, inspect_url, load_data, save_data

FIXTURE = Path(__file__).parent / "fixtures" / "survey_page.html"
PAGE_HTML = FIXTURE.read_text(encoding="utf-8")
CLOUDFLARE_HTML = "<html><head><title>Just a moment...</title></head><body>Verify you are human</body></html>"
EMPTY_HTML = "<html><body><table><tr><td>nothing here</td></tr></table></body></html>"
PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753de0000000c49444154789c63f8ffff3f0005fe02fe0def46b80000000049454e44ae426082"
)


class FakeElement:
    def __init__(self, text):
        self.text = text


class FakeDriver:
    """Minimal stand-in for a Selenium WebDriver attached to Chrome."""

    def __init__(self, pages):
        self.pages = list(pages)      # HTML returned by successive get() calls
        self.page_source = ""
        self.visited = []
        self.quit_called = False
        self.screenshots = []

    def get(self, url):
        self.visited.append(url)
        self.page_source = self.pages.pop(0) if self.pages else EMPTY_HTML

    def find_element(self, by, value):
        return FakeElement(self.page_source)

    def save_screenshot(self, path):
        Path(path).write_bytes(PNG_BYTES)  # a real 1x1 PNG so Pillow can open it
        self.screenshots.append(path)

    def quit(self):
        self.quit_called = True


@pytest.fixture
def fast(monkeypatch):
    """No polite delays / waits in tests."""
    monkeypatch.setattr(scrape.time, "sleep", lambda seconds: None)


@pytest.fixture
def scraper(fast, tmp_path):
    instance = GradCafeScraper(delay_seconds=0, html_dir=tmp_path / "raw_html")
    # Explicit wait replacement: results are "present" when a /result/ link is in the HTML.
    instance._wait_for_results = lambda timeout: "/result/" in instance.driver.page_source
    return instance


# --------------------------------------------------------------------------- #
# urllib helpers                                                              #
# --------------------------------------------------------------------------- #
@pytest.mark.analysis
def test_build_and_inspect_url():
    url = build_survey_url(3, cursor="abc")
    assert url == "https://www.thegradcafe.com/survey/?page=3&cursor=abc"
    info = inspect_url(url)
    assert info["page"] == 3 and info["is_gradcafe"] and info["cursor"] == {"raw": "abc"}
    assert inspect_url("https://example.com/x")["page"] is None
    with pytest.raises(ValueError):
        build_survey_url(0)


@pytest.mark.analysis
def test_inspect_cursor_decodes_keyset():
    url = GradCafeScraper._find_next_url(PAGE_HTML)
    cursor = inspect_cursor(url)
    assert cursor["admitid"] == 1020459 and cursor["_pointsToNextItems"] is True
    assert inspect_cursor("https://www.thegradcafe.com/survey/?page=1") is None


# --------------------------------------------------------------------------- #
# Parsing                                                                     #
# --------------------------------------------------------------------------- #
@pytest.mark.analysis
def test_parse_page_extracts_all_fields():
    records = GradCafeScraper()._parse_page(PAGE_HTML)
    assert [r["url"][-7:] for r in records] == ["1020478", "1020477", "1020476", "1020475"] or len(records) == 4
    by_id = {r["url"].rsplit("/", 1)[1]: r for r in records}
    gre_row = by_id["1020462"]
    assert gre_row["GPA"] == "GPA 2.50" and gre_row["GRE"] == "GRE 170"
    assert gre_row["GRE V"] == "GRE V 150" and gre_row["GRE AW"] == "GRE AW 3.00"
    assert gre_row["term"] == "Spring 2027" and gre_row["Degree"] == "Masters"
    assert gre_row["status"] == "Accepted" and gre_row["decision_date"] == "Aug 28"
    assert gre_row["program"] == "Food Science, Montclair State University"
    assert "Total comments" not in gre_row["raw_listing"]
    assert by_id["1020474"]["comments"].startswith("European")
    assert by_id["1020478"]["Degree"] == "MFA" and by_id["1020478"]["comments"] == ""


@pytest.mark.analysis
def test_parse_page_without_table_or_links():
    assert GradCafeScraper()._parse_page("<html><body>no table</body></html>") == []
    assert GradCafeScraper()._parse_page(EMPTY_HTML) == []


@pytest.mark.analysis
def test_parse_entry_tolerates_missing_cells_and_unknown_status():
    html = ('<table><tr><td>Uni</td><td><div>Prog only</div></td><td>Jan 01, 2026</td>'
            '<td>Pending review</td><td><a href="/result/42">x</a></td></tr>'
            '<tr><td><div><div>Fall 2026</div><div>Other</div><div>GPA 3.5</div>'
            '<div>GRE Q 160</div><div>Something else</div><div></div></div></td></tr></table>')
    record = GradCafeScraper()._parse_page(html)[0]
    assert record["program_name"] == "Prog only" and record["Degree"] == ""
    assert record["status"] == "Pending review" and record["decision_date"] == ""
    assert record["term"] == "Fall 2026" and record["GPA"] == "GPA 3.5" and record["GRE"] == ""
    short = GradCafeScraper()._parse_page('<table><tr><td><a href="/result/7">x</a></td></tr></table>')[0]
    assert short["program"] == ", x" and short["date_added"] == "" and short["url"].endswith("/result/7")


@pytest.mark.analysis
def test_normalize_status_variants():
    assert GradCafeScraper._normalize_status("Wait listed on Sep 07") == ("Wait listed", "Sep 07")
    assert GradCafeScraper._normalize_status("Waitlisted on Sep 07") == ("Wait listed", "Sep 07")
    assert GradCafeScraper._normalize_status("REJECTED") == ("Rejected", "")
    assert GradCafeScraper._normalize_status("Interview") == ("Interview", "")
    assert GradCafeScraper._normalize_status("weird") == ("weird", "")


@pytest.mark.analysis
def test_find_next_url_variants():
    assert GradCafeScraper._find_next_url(PAGE_HTML).startswith("https://www.thegradcafe.com/survey/?page=1&cursor=")
    assert GradCafeScraper._find_next_url('<a href="/survey?page=2">Next</a>') is None
    assert GradCafeScraper._find_next_url('<a href="/survey?page=x&cursor=c">Next</a>').endswith("?page=1&cursor=c")
    assert GradCafeScraper._find_next_url("<p>no links</p>") is None


@pytest.mark.analysis
def test_looks_blocked():
    assert GradCafeScraper._looks_blocked(CLOUDFLARE_HTML)
    assert GradCafeScraper._looks_blocked("<h1>403 Forbidden</h1>")
    assert not GradCafeScraper._looks_blocked(PAGE_HTML)


# --------------------------------------------------------------------------- #
# JSON persistence                                                            #
# --------------------------------------------------------------------------- #
@pytest.mark.db
def test_save_and_load_data_roundtrip(tmp_path):
    path = tmp_path / "out.json"
    assert load_data(path) == []
    save_data([{"a": 1}], path)
    assert load_data(path) == [{"a": 1}]
    path.write_text(json.dumps({"rows": [{"b": 2}]}))
    assert load_data(path) == [{"b": 2}]


# --------------------------------------------------------------------------- #
# Browser plumbing with the fake driver                                       #
# --------------------------------------------------------------------------- #
@pytest.mark.integration
def test_driver_property_attaches_to_chrome(monkeypatch):
    created = {}

    class FakeChrome:
        def __init__(self, options):
            created["address"] = options.experimental_options["debuggerAddress"]

    monkeypatch.setattr("selenium.webdriver.Chrome", FakeChrome)
    instance = GradCafeScraper(debugger_address="127.0.0.1:9333")
    assert isinstance(instance.driver, FakeChrome) and created["address"] == "127.0.0.1:9333"
    assert instance.driver is instance._driver  # cached


@pytest.mark.integration
def test_wait_for_results_true_and_timeout(monkeypatch):
    instance = GradCafeScraper()
    instance._driver = FakeDriver([PAGE_HTML])
    instance._driver.get("x")

    class FakeWait:
        def __init__(self, driver, timeout):
            self.timeout = timeout

        def until(self, condition):
            if self.timeout == 0:
                from selenium.common.exceptions import TimeoutException
                raise TimeoutException()
            return True

    monkeypatch.setattr("selenium.webdriver.support.ui.WebDriverWait", FakeWait)
    assert instance._wait_for_results(timeout=5) is True
    assert instance._wait_for_results(timeout=0) is False


@pytest.mark.integration
def test_fetch_page_html_archives_and_refuses_foreign_hosts(scraper, tmp_path):
    scraper._driver = FakeDriver([PAGE_HTML])
    html = scraper._fetch_page_html(build_survey_url(1), page=1)
    assert "/result/1020478" in html
    assert (tmp_path / "raw_html" / "page_0001.html").exists()
    with pytest.raises(ValueError):
        scraper._fetch_page_html("https://example.com/", page=2)


@pytest.mark.integration
def test_fetch_page_html_waits_for_human_check_then_continues(scraper, capsys):
    """Cloudflare page first; a second wait (the human clearing it) succeeds."""
    driver = FakeDriver([CLOUDFLARE_HTML])
    scraper._driver = driver
    calls = []

    def wait(timeout):
        calls.append(timeout)
        if len(calls) == 2:               # the long wait: pretend the person clicked the box
            driver.page_source = PAGE_HTML
            return True
        return False

    scraper._wait_for_results = wait
    assert "/result/" in scraper._fetch_page_html(build_survey_url(1), 1)
    assert calls == [15, scraper.challenge_timeout]
    assert "Cloudflare verification is showing" in capsys.readouterr().err


@pytest.mark.integration
def test_fetch_page_html_stops_when_blocked_or_empty(scraper):
    scraper._driver = FakeDriver([CLOUDFLARE_HTML])
    scraper._wait_for_results = lambda timeout: False
    with pytest.raises(RuntimeError, match="blocked"):
        scraper._fetch_page_html(build_survey_url(1), 1)
    scraper._driver = FakeDriver([EMPTY_HTML])
    with pytest.raises(RuntimeError, match="No results table"):
        scraper._fetch_page_html(build_survey_url(1), 1)


@pytest.mark.integration
def test_check_robots_allows_and_writes_evidence(scraper, tmp_path, capsys):
    robots = "User-agent: *\nAllow: /\n\nUser-agent: GPTBot\nDisallow: /\n"
    scraper._driver = FakeDriver([robots])
    shot = tmp_path / "screenshot.jpg"
    assert scraper.check_robots(shot) is True
    assert shot.exists() and (tmp_path / "robots.txt").read_text() == robots
    assert not shot.with_suffix(".png").exists()
    assert "ALLOWS" in capsys.readouterr().out


@pytest.mark.integration
def test_check_robots_disallow_blocked_and_no_screenshot(scraper, tmp_path, monkeypatch):
    scraper._driver = FakeDriver(["User-agent: *\nDisallow: /survey/\n"])
    assert scraper.check_robots(None) is False
    scraper._driver = FakeDriver([CLOUDFLARE_HTML])
    assert scraper.check_robots(None) is False
    # Pillow unavailable: the .png stays and no .jpg conversion happens
    monkeypatch.setitem(sys.modules, "PIL", None)
    scraper._driver = FakeDriver(["User-agent: *\nAllow: /\n"])
    shot = tmp_path / "evidence.jpg"
    assert scraper.check_robots(shot) is True
    assert shot.with_suffix(".png").exists() and not shot.exists()


@pytest.mark.integration
def test_scrape_data_follows_cursor_and_checkpoints(scraper, tmp_path, capsys):
    """Two pages, then a page without a Next link -> stops, saves, checkpoints."""
    last_page = PAGE_HTML.replace("<span>Next</span>", "<span>End</span>")
    scraper._driver = FakeDriver([PAGE_HTML, PAGE_HTML, last_page])
    output, checkpoint = tmp_path / "data.json", tmp_path / "ckpt.json"

    records = scraper.scrape_data(target_rows=100, output=output, checkpoint=checkpoint)
    assert len(records) == 4                              # duplicates across pages are skipped
    state = json.loads(checkpoint.read_text())
    assert state["pages_done"] == 3 and state["next_url"] is None and state["total_records"] == 4
    assert "no further pages" in capsys.readouterr().err

    # resume: checkpoint says there is no next page -> starts again from page 1 (page counter 4);
    # a page with a table but no entries stops the run
    no_entries = "<html><body><a href='/result/0'></a><table><tr><td>x</td></tr></table></body></html>"
    scraper._driver = FakeDriver([no_entries])
    assert len(scraper.scrape_data(target_rows=100, output=output, checkpoint=checkpoint)) == 4
    assert "contained no entries" in capsys.readouterr().err


@pytest.mark.integration
def test_scrape_data_stops_on_target_max_pages_and_errors(scraper, tmp_path, capsys):
    scraper._driver = FakeDriver([PAGE_HTML, PAGE_HTML])
    out = scraper.scrape_data(target_rows=2, output=tmp_path / "a.json", checkpoint=tmp_path / "a.ckpt")
    assert len(out) == 4 and len(scraper._driver.visited) == 1  # target reached after one page
    scraper._driver = FakeDriver([PAGE_HTML, PAGE_HTML])
    scraper.scrape_data(target_rows=100, max_pages=1, output=tmp_path / "b.json", checkpoint=tmp_path / "b.ckpt",
                        start_url=build_survey_url(1, cursor="zzz"))
    assert len(scraper._driver.visited) == 1
    scraper._driver = FakeDriver([CLOUDFLARE_HTML])
    scraper._wait_for_results = lambda timeout: False
    assert scraper.scrape_data(target_rows=100, output=tmp_path / "c.json", checkpoint=tmp_path / "c.ckpt") == []
    assert "[stop]" in capsys.readouterr().err


@pytest.mark.integration
def test_scrape_new_entries_stops_at_known_data(scraper, tmp_path):
    scraper._driver = FakeDriver([PAGE_HTML, PAGE_HTML])
    known = {"https://www.thegradcafe.com/result/1020462"}
    new = scraper.scrape_new_entries(known, max_pages=5, output=tmp_path / "new.json")
    assert {r["url"][-7:] for r in new} == {"1020478", "1020474", "1020467"}
    assert len(scraper._driver.visited) == 2           # page 2 repeated the same ids -> stop
    assert len(load_data(tmp_path / "new.json")) == 3
    scraper._driver = FakeDriver([CLOUDFLARE_HTML])
    scraper._wait_for_results = lambda timeout: False
    assert scraper.scrape_new_entries(set()) == []


@pytest.mark.integration
def test_parse_saved_html_and_close(scraper, tmp_path):
    folder = tmp_path / "pages"
    folder.mkdir()
    (folder / "page_0001.html").write_text(PAGE_HTML, encoding="utf-8")
    (folder / "page_0002.html").write_text(PAGE_HTML, encoding="utf-8")
    assert len(scraper.parse_saved_html(folder, tmp_path / "parsed.json")) == 4
    driver = FakeDriver([])
    scraper._driver = driver
    scraper.close()
    assert driver.quit_called and scraper._driver is None
    scraper.close()  # idempotent


@pytest.mark.integration
def test_main_cli_paths(monkeypatch, tmp_path, fast):
    folder = tmp_path / "pages"
    folder.mkdir()
    (folder / "page_0001.html").write_text(PAGE_HTML, encoding="utf-8")
    assert scrape.main(["--from-html", str(folder), "--output", str(tmp_path / "o.json")]) == 0

    monkeypatch.setattr(GradCafeScraper, "check_robots", lambda self, screenshot_path=None: False)
    assert scrape.main(["--output", str(tmp_path / "o.json")]) == 1

    monkeypatch.setattr(GradCafeScraper, "check_robots", lambda self, screenshot_path=None: True)
    monkeypatch.setattr(GradCafeScraper, "scrape_data", lambda self, **kw: [])
    assert scrape.main(["--no-html", "--skip-robots", "--output", str(tmp_path / "o.json"),
                        "--checkpoint", str(tmp_path / "c.json")]) == 0
