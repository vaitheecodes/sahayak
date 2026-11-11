"""HTML cleaning and heading-based chunking (kb_ingester/clean.py, chunking.py)."""

from __future__ import annotations

from kb_ingester import chunking
from kb_ingester.clean import html_to_text, plain_to_text, to_text
from tests.kb_ingest_helpers import LEAVE_PAGE


def test_page_furniture_is_removed_and_the_article_kept():
    doc = html_to_text(LEAVE_PAGE.encode())
    assert doc.title == "Apply for leave - Brightdesk Help"
    assert doc.text.startswith("# Apply for leave\n")
    for gone in ("Home", "cookies", "Copyright", "track()"):
        assert gone not in doc.text
    assert "## Steps" in doc.text
    assert "1. Open the Leave module from the left menu.\n2. Click Apply Leave" in doc.text


def test_noise_by_role_and_class_and_hidden_elements_go():
    html = b"""<body><div role="navigation">Menu</div><div id="gdpr-consent">Consent</div>
    <div class="share-buttons">Share</div><div aria-hidden="true">Hidden</div><p hidden>Also hidden</p>
    <div class="content"><p>Real text.</p></div><aside>Related</aside><form>Search</form></body>"""
    assert html_to_text(html).text == "Real text."


def test_a_page_header_goes_but_an_articles_header_with_its_title_stays():
    html = b"""<body><header><a>Logo</a></header><article><header><h1>Title</h1></header>
    <p>Body.</p></article></body>"""
    assert html_to_text(html).text == "# Title\n\nBody."


def test_lists_tables_and_pre_are_rendered():
    html = b"""<main><h2>Setup</h2><ul><li>One</li><li><p>Two</p><ol><li>Sub</li></ol></li></ul>
    <table><tr><th>Plan</th><th>Users</th></tr><tr><td>Basic</td><td>10</td></tr></table>
    <pre>line 1
  line 2</pre><h4>Small heading</h4><p>Text</p></main>"""
    text = html_to_text(html).text
    assert "## Setup" in text and "- One\n- Two\n  1. Sub" in text
    assert "Plan | Users\nBasic | 10" in text
    assert "line 1\n  line 2" in text
    assert "\nSmall heading\n" in text and "#### " not in text


def test_charset_from_the_header_is_used():
    assert "café" in html_to_text("<p>café</p>".encode("latin-1"), "latin-1").text


def test_plain_text_and_markdown_pass_through():
    doc = plain_to_text(b"# Guide\r\n\r\n\r\n\r\nStep   one\n")
    assert doc.title == "Guide" and doc.text == "# Guide\n\nStep one"
    assert to_text(b"# A", "text/markdown").text == "# A"


def _words(n: int, word: str = "word") -> str:
    return " ".join([word] * n)


def test_sections_get_heading_paths():
    text = f"# Leave\n{_words(400)}\n## Apply\n{_words(400)}\n### Mobile\n{_words(400)}\n## Cancel\n{_words(400)}"
    chunks, capped = chunking.chunk_text(text)
    assert [c.heading_path for c in chunks] == ["Leave", "Leave > Apply", "Leave > Apply > Mobile", "Leave > Cancel"]
    assert capped == 0 and [c.ordinal for c in chunks] == [1, 2, 3, 4]
    assert chunks[1].text.startswith("## Apply")


def test_small_sections_are_merged():
    text = "# Leave\nintro\n## Apply\n" + _words(50) + "\n## Cancel\n" + _words(50)
    chunks, _ = chunking.chunk_text(text)
    assert len(chunks) == 1 and chunks[0].heading_path == "Leave" and "## Cancel" in chunks[0].text


def test_a_long_section_is_split_at_blank_lines():
    paragraphs = "\n\n".join(_words(500, f"p{i}") for i in range(4))
    chunks, _ = chunking.chunk_text(f"# Big\n{paragraphs}")
    assert len(chunks) == 2 and all(c.heading_path == "Big" for c in chunks)
    assert all(len(c.text.split()) <= chunking.MAX_WORDS + 1 for c in chunks)


def test_chunks_over_the_cap_are_counted():
    text = "\n".join(f"# S{i}\n{_words(400)}" for i in range(chunking.MAX_CHUNKS + 3))
    chunks, capped = chunking.chunk_text(text)
    assert len(chunks) == chunking.MAX_CHUNKS and capped == 3


def test_hashes_ignore_whitespace_but_not_words():
    assert chunking.chunk_hash("A", "one  two\n") == chunking.chunk_hash("A", "one two")
    assert chunking.chunk_hash("A", "one two") != chunking.chunk_hash("B", "one two")
    assert chunking.content_hash("x y") != chunking.content_hash("x z")


def test_heading_permalink_anchors_are_dropped():
    html = '<main><h2>Managing <code>pip</code><a class="headerlink" href="#p">¶</a></h2><h3>Setup #</h3></main>'
    assert html_to_text(html.encode()).text == "## Managing pip\n\n### Setup"


def test_a_list_item_is_one_line_whatever_its_paragraphs():
    html = b"""<main><ol start="3"><li><p>Pick the dates.</p><p>Click <b>Apply</b>.</p>
    <ul><li>Morning</li><li>Afternoon</li></ul></li><li>Click Save.</li></ol></main>"""
    assert html_to_text(html).text == "3. Pick the dates. Click Apply.\n  - Morning\n  - Afternoon\n4. Click Save."


def test_the_comma_left_by_a_removed_icon_is_closed_up():
    html = b'<main><ol><li>In the corner, select <svg><path/></svg>, then click New.</li></ol></main>'
    assert html_to_text(html).text == "1. In the corner, select, then click New."


def test_table_cells_keep_their_inline_text_together():
    html = b"<table><tr><td><code>https://</code><code>example.com/new</code></td><td><p>a</p><p>b</p></td></tr></table>"
    assert html_to_text(html).text == "`https://example.com/new` | a b"
