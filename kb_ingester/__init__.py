"""Builds the knowledge base from a product's own public content.

  safe_fetch.py   SafeFetcher: http(s) GET that can't reach private or
                  internal addresses (checked IP pinned, redirects
                  re-checked, size/time/type limits, per-host pacing)
  sources.py      the Source interface and UrlSource (one page, robots.txt)
  clean.py        HTML -> text with "#" headings (navigation, scripts,
                  cookie banners and other page furniture removed)
  chunking.py     text -> heading sections of about 300-1,200 words
  checks.py       quote matching, paraphrase and prompt-injection checks
  drafting.py     one chunk -> validated draft entries, terms, a category
  dedupe.py       near-duplicate flagging against existing entries
  runs.py         sources, estimates, runs, model-call caps, storage
  review.py       the reviewer's side: edit, approve, reject, terms, categories
  api.py          /api/kb/* (managers and technicians; never the admin)
  mock_drafts.py  what the offline mock AI provider drafts (local demo)

Pages are never stored whole: a document keeps only its hash, chunk text
is kept until its drafts are decided (or the retention period ends), and
an entry keeps a paraphrased answer, short quotes and the source link.
"""
