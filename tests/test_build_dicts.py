#!/usr/bin/env python3
"""Tests for build_dicts.py. Run with:  python3 -m unittest discover -s tests

Zero dependencies (stdlib unittest). Several tests are regressions for bugs hit
while developing the builder; they are labelled REGRESSION.
"""
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))
import build_dicts as bd  # noqa: E402

COMPANION = REPO_ROOT / "Blood_Meridian_Vocabulary_Companion.epub"


def visible_words(html_str):
    """Lowercase word tokens of the rendered text (tags + entities stripped)."""
    s = re.sub(r"<[^>]+>", " ", html_str)
    s = (s.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
          .replace("&#8212;", " ").replace("&#160;", " "))
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).split()


class TestEscaping(unittest.TestCase):
    def test_xml_escape(self):
        self.assertEqual(bd.xml_escape('a < b & c > d'), 'a &lt; b &amp; c &gt; d')

    def test_xml_escape_leaves_quotes(self):
        self.assertEqual(bd.xml_escape('say "hi"'), 'say "hi"')

    def test_attr_escape_escapes_quotes(self):
        self.assertEqual(bd.attr_escape('a"b&c'), 'a&quot;b&amp;c')

    def test_ascii_fold(self):
        self.assertEqual(bd.ascii_fold("café Zoöl"), "cafe Zool")

    def test_strip_tags(self):
        self.assertEqual(bd.strip_tags("<b>hi</b> <i>there</i>"), "hi there")


class TestInflections(unittest.TestCase):
    def test_add_s_rules(self):
        for base, plural in [("cat", "cats"), ("fox", "foxes"), ("church", "churches"),
                             ("lady", "ladies"), ("buzz", "buzzes")]:
            out = set()
            bd.add_s(base, out)
            self.assertIn(plural, out, f"{base} -> {plural}")

    def test_gen_infl_includes_base_and_plural(self):
        forms = bd.gen_infl("wolf")
        self.assertIn("wolf", forms)
        self.assertIn("wolfs", forms)

    def test_no_double_pluralization(self):
        # REGRESSION: a word already ending in 's' must not become '...ses'
        self.assertNotIn("aborigineses", bd.gen_infl("aborigines"))


class TestLookupKeys(unittest.TestCase):
    def test_single_word(self):
        primary, forms = bd.lookup_keys("meridian")
        self.assertEqual(primary, "meridian")
        self.assertIn("meridians", forms)

    def test_multiword_salient_tokens(self):
        primary, forms = bd.lookup_keys("prairie wolf")
        self.assertIn("prairie", forms)
        self.assertIn("wolf", forms)
        self.assertIn("prairiewolf", forms)  # de-spaced whole

    def test_hyphenated_dehyphenated(self):
        _, forms = bd.lookup_keys("self-murder")
        self.assertIn("selfmurder", forms)

    def test_empty_returns_none(self):
        self.assertEqual(bd.lookup_keys("123 -"), (None, set()))


class TestStyleText(unittest.TestCase):
    def test_quote_dimmed(self):
        self.assertIn('<span class="qt">"x"</span>', bd._style_text('a "x" b'))

    def test_leading_label_italic(self):
        self.assertTrue(bd._style_text("(Astron.) a circle").startswith('<i class="lbl">(Astron.)</i>'))

    def test_status_tag(self):
        self.assertIn('<span class="tag">[Obs.]</span>', bd._style_text("gone [Obs.]"))

    def test_no_attribute_quote_collision(self):
        # REGRESSION: the quote-dimming pass must not match the quotes inside the
        # class="..." attributes it (or the label/tag passes) insert.
        out = bd._style_text('(Law) a "q" thing [Obs.]')
        self.assertNotIn("class=<", out)
        self.assertNotIn('"qt">"tag"', out)
        self.assertIn('class="qt"', out)
        self.assertIn('class="tag"', out)
        self.assertIn('class="lbl"', out)

    def test_escapes_specials(self):
        out = bd._style_text("a < b & c")
        self.assertIn("&lt;", out)
        self.assertIn("&amp;", out)


class TestSplitSenses(unittest.TestCase):
    def test_three_senses(self):
        lead, senses = bd._split_senses("1. alpha 2. beta 3. gamma")
        self.assertEqual(lead, "")
        self.assertEqual(senses, ["alpha", "beta", "gamma"])

    def test_unnumbered(self):
        self.assertEqual(bd._split_senses("just a definition"), ("just a definition", []))

    def test_stray_number_not_split(self):
        # REGRESSION: numbering is walked sequentially (1 then 2 then ...), so a
        # stray citation number like "7." inside sense 1 must not start a new sense.
        lead, senses = bd._split_senses("1. see Deut. 7. fine 2. second")
        self.assertEqual(len(senses), 2)
        self.assertIn("7.", senses[0])


class TestPeelRunins(unittest.TestCase):
    def test_capitalized_subentry_peeled(self):
        main, phrases, syns = bd._peel_runins("a circle. -- First meridian, the base line.")
        self.assertEqual(main, "a circle.")
        self.assertEqual(phrases, ["First meridian, the base line."])
        self.assertEqual(syns, [])

    def test_lowercase_tail_kept_inline(self):
        main, phrases, syns = bd._peel_runins("vibrates; -- so called because it escapes")
        self.assertEqual(phrases, [])
        self.assertIn("so called because it escapes", main)

    def test_synonyms_section(self):
        main, phrases, syns = bd._peel_runins("to lessen. Syn. -- subside; decrease.")
        self.assertEqual(syns, ["subside; decrease."])
        self.assertNotIn("Syn.", main)

    def test_no_runins(self):
        self.assertEqual(bd._peel_runins("plain def"), ("plain def", [], []))


class TestRenderPhrase(unittest.TestCase):
    def test_lemma_bolded(self):
        out = bd._render_phrase("First meridian, the line from which.")
        self.assertTrue(out.startswith("<b>First meridian</b>"))


class TestWebBody(unittest.TestCase):
    def test_single_sense_unnumbered(self):
        out = bd.web_body("A small room in a church.")
        self.assertIn('<p class="s">A small room in a church.</p>', out)
        self.assertNotIn('class="n"', out)

    def test_continuous_renumbering_across_blocks(self):
        # two POS blocks each restarting at 1 -> one continuous 1..3 sequence
        out = bd.web_body("1. a\n\n1. b 2. c")
        self.assertEqual(out.count('class="n"'), 3)
        for n in ("1.", "2.", "3."):
            self.assertIn(f'<b class="n">{n}</b>', out)
        self.assertNotIn('<b class="n">4.</b>', out)
        self.assertEqual(out.count('class="s gap"'), 1)  # the block boundary

    def test_label_and_quote_styled(self):
        out = bd.web_body('1. (Astron.) a "circle" here 2. plain')
        self.assertIn('<i class="lbl">(Astron.)</i>', out)
        self.assertIn('<span class="qt">"circle"</span>', out)

    def test_lossless(self):
        # No definition word is dropped. Only intentional removals: collapsed
        # duplicate sense numbers (digits) and the literal "Syn." label.
        src = ('1. First sense with a "quote." Milton.\n\n'
               '1. Second block here. 2. (Geog.) third sense. '
               '-- First meridian, the base line. Syn. -- alpha; beta.')
        out_words = set(visible_words(bd.web_body(src)))
        for w in visible_words(src):
            if w.isdigit() or w == "syn":
                continue
            self.assertIn(w, out_words, f"dropped word: {w!r}")

    def test_fallback_never_raises(self):
        for weird in ["", "   ", "[", '"unterminated', "1." * 50]:
            out = bd.web_body(weird)
            self.assertIsInstance(out, str)
            self.assertTrue(out)


class TestBmBody(unittest.TestCase):
    def test_single_sense_no_number_no_double_paren(self):
        # REGRESSION: pos already contains its parens; must render <i>(noun)</i>,
        # not <i>((noun))</i>, and a single sense gets no "1."
        out = bd.bm_body([{"pos": "(noun)", "def": "High point.", "quote": '"q"'}], header=False)
        self.assertIn("<i>(noun)</i>", out)
        self.assertNotIn("((", out)
        self.assertNotIn("<b>1.", out)

    def test_multi_sense_numbered(self):
        out = bd.bm_body([{"pos": "", "def": "one", "quote": ""},
                          {"pos": "", "def": "two", "quote": ""}], header=False)
        self.assertIn("<b>1.</b>", out)
        self.assertIn("<b>2.</b>", out)

    def test_header(self):
        out = bd.bm_body([{"pos": "", "def": "x", "quote": ""}], header=True)
        self.assertIn("&#9656;", out)  # the ▸ Blood Meridian divider


class TestRenderEntry(unittest.TestCase):
    def test_orth_and_inflections(self):
        out = bd.render_entry({"primary": "wolf", "display": "Wolf",
                               "iforms": {"wolf", "wolves", "wolfs"}, "body": "<p>x</p>"})
        self.assertIn('<idx:orth value="wolf">', out)
        self.assertIn("<b>Wolf</b>", out)
        self.assertIn('<idx:iform value="wolves"/>', out)
        self.assertNotIn('<idx:iform value="wolf"/>', out)  # primary excluded from iforms

    def test_no_primary_returns_none(self):
        self.assertIsNone(bd.render_entry({"primary": None, "display": "X",
                                           "iforms": set(), "body": "<p>x</p>"}))


class TestEmitDict(unittest.TestCase):
    def test_writes_files_and_title(self):
        entries = [{"primary": "wolf", "display": "Wolf",
                    "iforms": {"wolf", "wolves"}, "body": "<p>a canine</p>"}]
        with tempfile.TemporaryDirectory() as d:
            n, f = bd.emit_dict(d, "My Test Dictionary", entries)
            self.assertEqual((n, f), (1, 1))
            opf = Path(d, "content.opf").read_text(encoding="utf-8")
            self.assertIn("<dc:title>My Test Dictionary</dc:title>", opf)
            self.assertIn("<DefaultLookupIndex>headword</DefaultLookupIndex>", opf)
            for name in ("content-0000.xhtml", "dict.css", "toc.ncx"):
                self.assertTrue(Path(d, name).exists(), name)
            content = Path(d, "content-0000.xhtml").read_text(encoding="utf-8")
            self.assertIn("idx:entry", content)


@unittest.skipUnless(COMPANION.exists(), "companion EPUB not present")
class TestParseBmIntegration(unittest.TestCase):
    def test_reads_entries_from_epub(self):
        groups, order = bd.parse_bm(COMPANION)
        self.assertGreater(len(groups), 1000)        # ~1,300 unique terms
        self.assertEqual(len(groups), len(order))
        self.assertIn("escapement", groups)          # a known epilogue term
        first = groups["escapement"]["senses"][0]
        self.assertTrue(first["quote"])              # carries its book quote


if __name__ == "__main__":
    unittest.main(verbosity=2)
