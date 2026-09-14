"""Tests for the parts of the pipeline that don't need an API key.

Run: .venv/bin/python -m unittest discover -s tests -v

This covers the logic that is easy to get quietly wrong — chunk stitching,
vocabulary selection, Mermaid escaping, view rendering — but it cannot tell
you whether the notes are any good. Only a real lecture does that.
"""

from __future__ import annotations

import unittest

from classnotes.deck import Deck, Slide
from classnotes.master import _normalise, next_version, sanitise_mermaid
from classnotes.transcribe import Segment, build_vocabulary_prompt, merge_chunk_segments
from classnotes.views import full, skim


def sample_deck() -> Deck:
    return Deck(
        source="test.pptx",
        slides=[
            Slide(1, "Market Segmentation", ["Dividing a heterogeneous market", "Four bases"]),
            Slide(2, "Psychographic Segmentation", ["Lifestyle and values", "VALS Framework"]),
            Slide(3, "Targeting Strategies", ["Harder than it looks", "Concentrated Marketing"]),
        ],
    )


class TestDeckTerms(unittest.TestCase):
    def test_keeps_multiword_phrases_and_acronyms(self):
        terms = sample_deck().terms()
        self.assertIn("Market Segmentation", terms)
        self.assertIn("Concentrated Marketing", terms)
        self.assertIn("VALS", terms)

    def test_drops_bullet_initial_single_words(self):
        """The budget is ~224 tokens. Spending it on 'Four' and 'Harder' —
        words ASR was never going to fumble — crowds out the real jargon."""
        terms = sample_deck().terms()
        for junk in ("Four", "Harder", "Dividing", "Lifestyle"):
            self.assertNotIn(junk, terms, f"{junk!r} should not reach the ASR prompt")

    def test_single_words_survive_from_titles(self):
        deck = Deck(source="t", slides=[Slide(1, "Positioning", ["Some body text here"])])
        self.assertIn("Positioning", deck.terms())

    def test_limit_is_respected(self):
        deck = Deck(
            source="t",
            slides=[Slide(i, f"Concept Number {i}", [f"Body Phrase {i}"]) for i in range(50)],
        )
        self.assertLessEqual(len(deck.terms(limit=10)), 10)


class TestVocabularyPrompt(unittest.TestCase):
    def test_stays_within_whisper_prompt_budget(self):
        prompt = build_vocabulary_prompt([f"Technical Term Number {i}" for i in range(200)])
        self.assertLessEqual(len(prompt), 700)

    def test_prefers_longest_terms(self):
        prompt = build_vocabulary_prompt(["AB", "Cross Price Elasticity Measurement", "CD"])
        self.assertIn("Cross Price Elasticity Measurement", prompt)

    def test_empty_input_gives_empty_prompt(self):
        self.assertEqual(build_vocabulary_prompt([]), "")


class TestChunkMerge(unittest.TestCase):
    def test_offsets_are_applied(self):
        merged = merge_chunk_segments(
            [(0.0, [Segment(0, 5, "one")]), (100.0, [Segment(20, 25, "two")])]
        )
        self.assertEqual([s.start for s in merged], [0.0, 120.0])

    def test_overlap_duplicate_is_dropped(self):
        """Chunk 0 covers 0-300; chunk 1 starts at 290 and re-hears 290-300."""
        merged = merge_chunk_segments(
            [
                (0.0, [Segment(290, 298, "seam words")]),
                (290.0, [Segment(0, 8, "seam words"), Segment(12, 18, "new words")]),
            ]
        )
        self.assertEqual([s.text for s in merged], ["seam words", "new words"])

    def test_segment_straddling_the_seam_is_kept(self):
        """Midpoint past the overlap means it's genuinely the later chunk's."""
        merged = merge_chunk_segments(
            [(0.0, [Segment(0, 5, "early")]), (290.0, [Segment(5, 25, "straddler")])]
        )
        self.assertIn("straddler", [s.text for s in merged])

    def test_output_is_time_ordered(self):
        merged = merge_chunk_segments(
            [(500.0, [Segment(0, 5, "late")]), (0.0, [Segment(0, 5, "early")])]
        )
        self.assertEqual([s.text for s in merged], ["early", "late"])

    def test_no_chunks_is_not_an_error(self):
        self.assertEqual(merge_chunk_segments([]), [])


class TestMermaid(unittest.TestCase):
    def test_valid_input_is_untouched(self):
        source = 'flowchart TD\n    n1["Alpha"] --> n2["Beta"]'
        self.assertEqual(sanitise_mermaid(source), source)

    def test_unquoted_labels_get_quoted(self):
        self.assertIn('n1["Alpha"]', sanitise_mermaid("flowchart TD\n    n1[Alpha] --> n2[Beta]"))

    def test_label_breaking_characters_are_stripped(self):
        out = sanitise_mermaid('flowchart TD\n    n1["Price (elastic)"] --> n2["Cost #2"]')
        for char in "()#":
            self.assertNotIn(char, out)

    def test_edge_labels_survive(self):
        out = sanitise_mermaid('flowchart TD\n    n1["A"] -->|"leads to"| n2["B"]')
        self.assertIn('-->|"leads to"|', out)

    def test_missing_header_is_added(self):
        self.assertTrue(sanitise_mermaid('n1["A"] --> n2["B"]').startswith("flowchart TD"))

    def test_empty_stays_empty(self):
        self.assertEqual(sanitise_mermaid(""), "")
        self.assertEqual(sanitise_mermaid("   "), "")


class TestNormalise(unittest.TestCase):
    def test_empty_payload_does_not_crash(self):
        artifact = _normalise({})
        self.assertEqual(artifact["summary"]["sections"], [])
        self.assertEqual(artifact["key_terms"], [])

    def test_invalid_coverage_falls_back_to_normal(self):
        artifact = _normalise({"concepts": [{"name": "X", "coverage": "nonsense"}]})
        self.assertEqual(artifact["concepts"][0]["coverage"], "normal")

    def test_unnamed_entries_are_dropped(self):
        artifact = _normalise(
            {"key_terms": [{"term": "", "definition": "d"}, {"term": "Real", "definition": "d"}]}
        )
        self.assertEqual([t["term"] for t in artifact["key_terms"]], ["Real"])

    def test_non_integer_slide_refs_are_discarded(self):
        artifact = _normalise(
            {"summary": {"sections": [{"heading": "H", "slide_refs": [1, "two", None, 3]}]}}
        )
        self.assertEqual(artifact["summary"]["sections"][0]["slide_refs"], [1, 3])


def sample_artifact() -> dict:
    artifact = _normalise(
        {
            "summary": {
                "headline": "How segmentation leads to positioning.",
                "sections": [
                    {
                        "heading": "Market Segmentation",
                        "slide_refs": [1, 2],
                        "time_range": "00:00:00-00:12:00",
                        "points": [f"Point number {i} with enough words to be a sentence." for i in range(5)],
                        "lecturer_stress": "This comes up in the exam.",
                    }
                ],
            },
            "diagram": {"mermaid": 'flowchart TD\n    n1["Segment"] --> n2["Target"]'},
            "key_terms": [{"term": f"Term {i}", "definition": "A definition."} for i in range(12)],
            "concepts": [{"name": "Price Elasticity", "weight": 0.8, "coverage": "rushed"}],
            "exam_signals": {"stressed": ["Elasticity"], "likely_questions": ["Define it."]},
            "open_threads": ["Someone asked about B2B and it was not answered."],
        }
    )
    artifact["session"] = {"course": "Marketing", "topic": "Segmentation", "date": "2026-09-14"}
    artifact["generated_by"] = {"provider": "anthropic", "model": "claude-opus-5"}
    artifact["version"] = 1
    artifact["videos"] = [
        {"concept": "Price Elasticity", "why": "rushed", "query": "q",
         "search_url": "https://example.com", "links": []}
    ]
    return artifact


class TestViews(unittest.TestCase):
    def setUp(self):
        self.artifact = sample_artifact()

    def test_skim_is_materially_shorter_than_full(self):
        self.assertLess(
            len(skim.render(self.artifact)), len(full.render(self.artifact)) * 0.8
        )

    def test_skim_caps_points_and_terms(self):
        rendered = skim.render(self.artifact)
        self.assertNotIn("Point number 4", rendered)   # only 2 points per section
        self.assertNotIn("Term 11", rendered)          # only 8 terms
        self.assertIn("and 4 more", rendered)

    def test_full_keeps_everything(self):
        rendered = full.render(self.artifact)
        self.assertIn("Point number 4", rendered)
        self.assertIn("Term 11", rendered)
        self.assertIn("Left open", rendered)

    def test_both_carry_the_diagram(self):
        for rendered in (skim.render(self.artifact), full.render(self.artifact)):
            self.assertIn("```mermaid", rendered)

    def test_both_warn_against_editing(self):
        for rendered in (skim.render(self.artifact), full.render(self.artifact)):
            self.assertIn("Do not edit this file", rendered)

    def test_fake_provider_output_is_stamped(self):
        self.artifact["generated_by"] = {"provider": "fake", "model": "fake-deterministic-v0"}
        self.assertIn("Placeholder output", full.render(self.artifact))

    def test_search_link_used_when_api_returned_nothing(self):
        self.assertIn("Search YouTube", full.render(self.artifact))

    def test_renders_with_a_nearly_empty_artifact(self):
        bare = _normalise({})
        bare["session"] = {}
        bare["generated_by"] = {}
        for renderer in (skim.render, full.render):
            self.assertTrue(renderer(bare).strip())


class TestRealWorldDecks(unittest.TestCase):
    """Regressions found by running deck parsing over 70 real-world PDFs.

    Everything here failed on an actual file before it was a test.
    """

    def test_all_caps_headings_do_not_flood_the_vocabulary(self):
        """ALL-CAPS slide titles are the norm in plenty of university decks.
        Matching every 2-6 letter caps run put THE/OF/AND in the ASR prompt at
        the acronym weight bonus, outranking the real jargon."""
        deck = Deck(
            source="t",
            slides=[Slide(1, "THE BASICS OF MARKET SEGMENTATION AND TARGETING", ["Body"])],
        )
        terms = deck.terms()
        for noise in ("THE", "OF", "AND"):
            self.assertNotIn(noise, terms)

    def test_real_acronyms_survive_the_filter(self):
        deck = Deck(source="t", slides=[Slide(1, "The VALS and SWOT Frameworks", [])])
        terms = deck.terms()
        self.assertIn("VALS", terms)
        self.assertIn("SWOT", terms)

    def test_image_only_deck_is_flagged_not_silently_accepted(self):
        deck = Deck(source="t", slides=[Slide(i, "", []) for i in range(1, 21)])
        self.assertTrue(deck.looks_scanned)

    def test_deck_with_real_text_is_not_flagged(self):
        self.assertFalse(sample_deck().looks_scanned)

    def test_empty_deck_is_flagged(self):
        self.assertTrue(Deck(source="t", slides=[]).looks_scanned)

    def _write_pdf(self, path, user_password):
        from pypdf import PdfWriter

        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        writer.encrypt(user_password=user_password, owner_password="ownerpass")
        with path.open("wb") as handle:
            writer.write(handle)

    def test_permission_restricted_pdf_opens(self):
        """Faculty 'protected' exports are encrypted with an empty user
        password. These used to crash with FileNotDecryptedError."""
        import tempfile
        from pathlib import Path

        from classnotes.deck import load

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "protected.pdf"
            self._write_pdf(path, user_password="")
            load(path)  # must not raise

    def test_password_locked_pdf_gives_an_actionable_error(self):
        import tempfile
        from pathlib import Path

        from classnotes.deck import load

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "locked.pdf"
            self._write_pdf(path, user_password="secret123")
            with self.assertRaises(ValueError) as caught:
                load(path)
            self.assertIn("password-protected", str(caught.exception))


class TestSiteMarkdown(unittest.TestCase):
    """The static site converts the markdown the views already emit, so the
    web page and the file you paste into WhatsApp can never drift apart."""

    def convert(self, source, **kwargs):
        from classnotes.site import markdown_to_html

        return markdown_to_html(source, **kwargs)

    def test_page_title_h1_is_dropped(self):
        """The page supplies its own header; a second one is duplication."""
        self.assertNotIn("<h1>", self.convert("# Course — Topic\n\ntext"))
        self.assertIn("<h1>", self.convert("# Course — Topic", skip_h1=False))

    def test_consecutive_bullets_become_one_list(self):
        out = self.convert("- one\n- two\n- three")
        self.assertEqual(out.count("<ul>"), 1)
        self.assertEqual(out.count("<li>"), 3)

    def test_table_converts_and_drops_the_divider_row(self):
        out = self.convert("| Term | Slide |\n|---|---|\n| **VALS** | 6 |")
        self.assertIn("<th>Term</th>", out)
        self.assertIn("<td><strong>VALS</strong></td>", out)
        self.assertNotIn("---", out)

    def test_mermaid_fence_keeps_its_class_for_rendering(self):
        out = self.convert('```mermaid\nflowchart TD\n    n1["A"] --> n2["B"]\n```')
        self.assertIn('<pre class="mermaid">', out)
        self.assertIn("flowchart TD", out)

    def test_blockquote_and_rule(self):
        out = self.convert("> the headline\n\n---")
        self.assertIn("<blockquote>the headline</blockquote>", out)
        self.assertIn("<hr>", out)

    def test_line_break_in_table_cell_survives(self):
        self.assertIn("<br>", self.convert("| a <br>b | c |\n|---|---|"))

    def test_model_output_cannot_inject_markup(self):
        """Terms and definitions come from a model. Angle brackets in them are
        text, not markup."""
        out = self.convert("- <script>alert(1)</script> and <img onerror=x>")
        self.assertNotIn("<script>", out)
        self.assertNotIn("<img", out)
        self.assertIn("&lt;script&gt;", out)

    def test_javascript_urls_are_stripped_to_plain_text(self):
        out = self.convert("- [click me](javascript:alert(1))")
        self.assertNotIn("javascript:", out)
        self.assertNotIn("<a ", out)
        self.assertIn("click me", out)

    def test_http_links_are_kept(self):
        out = self.convert("- [Khan Academy](https://youtube.com/watch?v=1)")
        self.assertIn('href="https://youtube.com/watch?v=1"', out)
        self.assertIn('rel="noopener"', out)

    def test_view_meta_line_is_not_printed_twice(self):
        """The page header already shows date/instructor/duration."""
        out = self.convert("# Course — Topic\n\n2026-09-11 · Prof. K · 72 min\n\n> headline")
        self.assertNotIn("Prof. K", out)
        self.assertIn("<blockquote>headline</blockquote>", out)

    def test_body_paragraphs_still_render(self):
        out = self.convert("# T\n\nmeta line\n\n## Section\n\nA real paragraph.")
        self.assertIn("<p>A real paragraph.</p>", out)

    def test_real_views_round_trip_without_leftover_markup(self):
        artifact = sample_artifact()
        for renderer in (skim.render, full.render):
            out = self.convert(renderer(artifact))
            self.assertNotIn("**", out)
            self.assertNotIn("\n| ", out)


class TestVersioning(unittest.TestCase):
    def test_versions_increment_and_never_overwrite(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            self.assertEqual(next_version(path), 1)
            (path / "master.v1.json").write_text("{}")
            (path / "master.v2.json").write_text("{}")
            self.assertEqual(next_version(path), 3)

    def test_latest_symlink_file_is_ignored_by_version_scan(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path / "master.latest.json").write_text("{}")
            self.assertEqual(next_version(path), 1)


if __name__ == "__main__":
    unittest.main()
