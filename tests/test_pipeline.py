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
