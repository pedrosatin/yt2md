#!/usr/bin/env python3
"""Offline tests for yt2md. No network, no LLM.

Run with:  python3 -m unittest -v test_yt2md
"""

import json
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path

yt = SourceFileLoader("yt2md", str(Path(__file__).parent / "yt2md")).load_module()


def cue(start_ms, dur_ms, text, append=False):
    ev = {"tStartMs": start_ms, "dDurationMs": dur_ms, "segs": [{"utf8": text}]}
    if append:
        ev["aAppend"] = 1
    return ev


def track(*events):
    return json.dumps({"events": list(events)})


class CleanText(unittest.TestCase):
    def test_strips_sound_annotations(self):
        self.assertEqual(yt.clean_text("hello [laughter] world", False), "hello world")
        self.assertEqual(yt.clean_text("[clears throat] ok", False), "ok")
        self.assertEqual(yt.clean_text("nice (APPLAUSE) day", False), "nice day")
        self.assertEqual(yt.clean_text("la ♪♪ la", False), "la la")

    def test_keeps_lowercase_parentheses(self):
        """Lowercase parentheticals are real speech, not annotations."""
        self.assertEqual(yt.clean_text("a (small aside) stays", False),
                         "a (small aside) stays")

    def test_keep_sound_tags_flag(self):
        self.assertEqual(yt.clean_text("hi [laughter]", True), "hi [laughter]")


class FormatSpeaker(unittest.TestCase):
    def test_bolds_short_names(self):
        self.assertEqual(yt.format_speaker("BOB: hello"), "**BOB:** hello")

    def test_ignores_long_prefixes(self):
        text = "this is a very long sentence that happens to contain: a colon"
        self.assertEqual(yt.format_speaker(text), text)


class Sanitize(unittest.TestCase):
    def test_removes_path_separators(self):
        self.assertEqual(yt.sanitize("a/b:c?d"), "a b c d")

    def test_never_returns_empty(self):
        self.assertEqual(yt.sanitize("..."), "video")

    def test_caps_length(self):
        self.assertLessEqual(len(yt.sanitize("x" * 500)), 180)


class YamlStr(unittest.TestCase):
    def test_escapes_quotes_and_backslashes(self):
        self.assertEqual(yt.yaml_str('say "hi"'), 'say \\"hi\\"')
        self.assertEqual(yt.yaml_str(r"C:\path"), r"C:\\path")

    def test_round_trips_hostile_titles(self):
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML not installed")
        for title in ['LIVE: Uncle Bob on "Fundamentals"', r'C:\x "y"', "acentos — 🚀"]:
            with self.subTest(title=title):
                parsed = yaml.safe_load(f'title: "{yt.yaml_str(title)}"')
                self.assertEqual(parsed["title"], title)


class ParseJson3(unittest.TestCase):
    def test_drops_aappend_duplicates(self):
        """The rolling effect of auto-captions repeats lines as aAppend events."""
        cues = yt.parse_json3(track(cue(0, 1000, "hello"),
                                    cue(0, 1000, "hello", append=True)), False)
        self.assertEqual([c[2] for c in cues], ["hello"])

    def test_end_time_uses_duration(self):
        cues = yt.parse_json3(track(cue(1000, 2500, "hi")), False)
        self.assertAlmostEqual(cues[0][0], 1.0)
        self.assertAlmostEqual(cues[0][1], 3.5)

    def test_splits_on_speaker_marker(self):
        cues = yt.parse_json3(track(cue(0, 1000, "one >> two >>> three")), False)
        self.assertEqual([(c[2], c[3]) for c in cues],
                         [("one", False), ("two", True), ("three", True)])

    def test_leading_marker_does_not_emit_empty_cue(self):
        cues = yt.parse_json3(track(cue(0, 1000, ">> only")), False)
        self.assertEqual([(c[2], c[3]) for c in cues], [("only", True)])

    def test_skips_events_without_segs(self):
        cues = yt.parse_json3(json.dumps({"events": [{"tStartMs": 0}]}), False)
        self.assertEqual(cues, [])


class ToMarkdown(unittest.TestCase):
    def test_joins_cues_that_run_together(self):
        cues = yt.parse_json3(track(cue(0, 2000, "ready to throw"),
                                    cue(2000, 2000, "down.")), False)
        self.assertEqual(yt.to_markdown(cues, False), "ready to throw down.")

    def test_breaks_on_real_silence(self):
        """The gap is measured from the previous cue's end, not its start."""
        cues = yt.parse_json3(track(cue(0, 2000, "first"),
                                    cue(10000, 2000, "second")), False)
        self.assertEqual(yt.to_markdown(cues, False), "first\n\nsecond")

    def test_breaks_on_speaker_change(self):
        cues = yt.parse_json3(track(cue(0, 2000, "mine >> yours")), False)
        self.assertEqual(yt.to_markdown(cues, False), "mine\n\nyours")

    def test_keep_timestamps(self):
        cues = yt.parse_json3(track(cue(3_661_000, 1000, "late")), False)
        self.assertEqual(yt.to_markdown(cues, True), "[01:01:01] late")


class PickTrack(unittest.TestCase):
    @staticmethod
    def info(language=None, manual=None, auto=None):
        return {"language": language, "subtitles": manual or {},
                "automatic_captions": auto or {}}

    @staticmethod
    def fmt(url):
        return [{"ext": "json3", "url": url}]

    def test_skips_machine_translations(self):
        """A 'tlang=' in the URL means YouTube generated the translation."""
        info = self.info("en", auto={
            "en": self.fmt("https://x/?lang=en&tlang=en"),
            "en-orig": self.fmt("https://x/?lang=en"),
        })
        self.assertEqual(yt.pick_track(info, None), ("en", "https://x/?lang=en"))

    def test_regional_variant_falls_back_to_base(self):
        info = self.info("en-US", auto={"en": self.fmt("https://x/en")})
        self.assertEqual(yt.pick_track(info, None)[0], "en")

    def test_multiple_orig_keys_are_dubs_not_originals(self):
        """A video with dubbed audio gets one '*-orig' per dub; they identify nothing."""
        info = self.info(None, manual={"en": self.fmt("https://x/en")},
                         auto={"ar-orig": self.fmt("https://x/ar"),
                               "en-orig": self.fmt("https://x/eno")})
        # Falls back to the first listed manual track rather than picking 'ar'.
        self.assertEqual(yt.pick_track(info, None)[0], "en")

    def test_override_allows_translation(self):
        info = self.info("en", auto={"pt": self.fmt("https://x/?tlang=pt")})
        self.assertEqual(yt.pick_track(info, "pt")[0], "pt")

    def test_raises_when_nothing_matches(self):
        with self.assertRaises(RuntimeError):
            yt.pick_track(self.info("en"), None)


class BuildDocument(unittest.TestCase):
    def test_frontmatter_then_heading(self):
        doc = yt.build_document("T", "C", "vid1", "en", ["a", "b"], "body text")
        head, _, rest = doc.partition("\n---\n\n")
        self.assertTrue(head.startswith("---\n"))
        self.assertIn('title: "T"', head)
        self.assertIn('author: "C"', head)
        self.assertIn("tags: [a, b]", head)
        self.assertIn("source_url: \"https://www.youtube.com/watch?v=vid1\"", head)
        self.assertEqual(rest, "# T\n\nbody text\n")

    def test_body_is_not_duplicated_in_header(self):
        """The old bullet header repeated channel/url already in the frontmatter."""
        doc = yt.build_document("T", "Chan", "v", "en", [], "text")
        self.assertEqual(doc.count("Chan"), 1)

    def test_empty_tags_render_as_empty_list(self):
        self.assertIn("tags: []", yt.build_document("T", "C", "v", "en", [], "x"))


if __name__ == "__main__":
    unittest.main()
