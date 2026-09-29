Operational notes
=================

Busy-state policy
-----------------

* One pull at a time.  ``POST /pull-data`` acquires :class:`flask_app.BusyState`
  atomically; a second request while busy is refused with
  ``409 {"busy": true}`` and does not start anything.
* ``POST /update-analysis`` never interferes with a running pull: while busy it
  answers ``409 {"busy": true}`` and performs no query; otherwise it re-queries
  and answers ``200 {"ok": true}``.  It never starts a scrape.
* The flag is always released in a ``finally`` block, including when the pull
  fails, so an error can never leave the page permanently "busy".
* The page polls ``GET /status`` every three seconds while a pull runs and
  re-enables the button when it finishes.
* The state is in-process.  Running several Flask workers would need a shared
  lock (for example a PostgreSQL advisory lock); the single-process deployment
  used here does not.

Idempotency strategy
--------------------

* **Uniqueness key:** ``p_id`` = the numeric id in the Grad Cafe entry URL,
  the table's primary key; ``url`` is additionally ``UNIQUE``.
* Inserts use ``ON CONFLICT (p_id) DO NOTHING``: re-loading the seed file,
  pulling the same entries twice, or overlapping pulls never duplicate or
  overwrite a row.  Existing rows are never updated by the pipeline.
* The scraper stops at the first page that contributes no unseen entry, so a
  pull normally reads only the pages that hold new submissions.
* Rows without a parseable ``/result/<id>`` URL are skipped (they cannot be
  identified uniquely).

Data conventions
----------------

* Missing values are stored as SQL ``NULL``; optional metrics never make an
  insert fail.
* A metric counts as *provided* only when the value is possible on its scale
  (GRE Q/V 130–170, GRE AW 0–6, GPA 0–4.0).  Grad Cafe's badge is labelled
  just "GRE" and is frequently filled with a combined total, and placeholders
  such as ``9.99`` occur; the range rule keeps the averages meaningful.
* Percentages are rendered with exactly two decimals everywhere (console, PDF
  and web page); counts are whole numbers.
