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

    def test_caps_length_in_bytes(self):
        self.assertEqual(len(yt.sanitize("x" * 500).encode("utf-8")), yt.MAX_STEM_BYTES)

    def test_long_cjk_and_emoji_titles_fit_and_are_not_split(self):
        for title in ["日本語のとても長いタイトル" * 40, "🚀🎉" * 200, "a" + "é" * 300]:
            with self.subTest(title=title[:8]):
                name = yt.sanitize(title)
                self.assertLessEqual(len(name.encode("utf-8")), yt.MAX_STEM_BYTES)
                self.assertNotIn("\ufffd", name)
                self.assertTrue(title.startswith(name))

    def test_long_title_can_be_written(self):
        import tempfile
        stem = yt.output_stem("日本語のタイトル🚀" * 60, "abcdefghijk")
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / f"{stem}.md").write_text("other")
            dest = yt.write_output(d, stem, "x")
            self.assertEqual(dest.name, f"{stem}-2.md")
            self.assertLessEqual(len(dest.name.encode("utf-8")), 255)

    def test_reserved_long_title_keeps_the_id_within_the_limit(self):
        stem = yt.output_stem("CLAUDE." + "ü" * 300, "abcdefghijk")
        self.assertTrue(stem.endswith("-abcdefghijk"))
        self.assertLessEqual(len(stem.encode("utf-8")), yt.MAX_STEM_BYTES)


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


class ResolveAgyModel(unittest.TestCase):
    def test_default_when_empty_or_none(self):
        self.assertEqual(yt.resolve_agy_model(None), "gemini-3.8-flash-high")
        self.assertEqual(yt.resolve_agy_model(""), "gemini-3.8-flash-high")

    def test_normalizes_gemini_flash(self):
        self.assertEqual(yt.resolve_agy_model("gemini-3.8-flash"), "gemini-3.8-flash-high")
        self.assertEqual(yt.resolve_agy_model("gemini 3.8 flash"), "gemini-3.8-flash-high")
        self.assertEqual(yt.resolve_agy_model("gemini-3.7-flash"), "gemini-3.7-flash-high")

    def test_normalizes_any_gemini_without_effort(self):
        self.assertEqual(yt.resolve_agy_model("gemini-3.8-pro"), "gemini-3.8-pro-high")
        self.assertEqual(yt.resolve_agy_model("gemini-3.9-flash"), "gemini-3.9-flash-high")
        self.assertEqual(yt.resolve_agy_model("gemini-2.5-pro"), "gemini-2.5-pro-high")
        self.assertEqual(yt.resolve_agy_model("gemini-pro"), "gemini-pro-high")

    def test_preserves_explicit_effort(self):
        self.assertEqual(yt.resolve_agy_model("gemini-3.8-flash-medium"), "gemini-3.8-flash-medium")
        self.assertEqual(yt.resolve_agy_model("gemini-3.8-flash-low"), "gemini-3.8-flash-low")
        self.assertEqual(yt.resolve_agy_model("gemini-3.8-flash-high"), "gemini-3.8-flash-high")
        self.assertEqual(yt.resolve_agy_model("gemini-3.1-pro-medium"), "gemini-3.1-pro-medium")

    def test_other_models_untouched(self):
        self.assertEqual(yt.resolve_agy_model("claude-sonnet-4-6"), "claude-sonnet-4-6")
        self.assertEqual(yt.resolve_agy_model("gpt-4o"), "gpt-4o")
        self.assertEqual(yt.resolve_agy_model("llama3.2"), "llama3.2")

    def test_cli_default_returns_none(self):
        self.assertIsNone(yt.resolve_agy_model("default"))
        self.assertIsNone(yt.resolve_agy_model("cli-default"))


class AgyHarness(unittest.TestCase):
    def test_registered_as_default(self):
        self.assertEqual(yt.DEFAULT_HARNESS, "agy")
        self.assertIn("agy", yt.HARNESSES)

    def test_build_default(self):
        build = yt.HARNESSES["agy"]["build"]
        self.assertEqual(build("gemini-3.8-flash-high"),
                         ["agy", "--model", "gemini-3.8-flash-high", "-p"])
        self.assertEqual(build("gemini-3.8-flash"),
                         ["agy", "--model", "gemini-3.8-flash-high", "-p"])
        self.assertEqual(build("default"), ["agy", "-p"])


class ConfigManagement(unittest.TestCase):
    def test_load_and_save_config(self):
        import tempfile
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_file = Path(tmpdir) / "config.json"
            cfg_dir = Path(tmpdir)
            with patch.object(yt, "CONFIG_FILE", cfg_file), \
                 patch.object(yt, "CONFIG_DIR", cfg_dir), \
                 patch.dict(yt.os.environ, {}, clear=True):
                # Empty initially
                self.assertEqual(yt.load_config(), {})

                # Save updates
                saved = yt.save_config({"tag_harness": "agy", "tag_model": "gemini-3.8-flash-high"})
                self.assertTrue(saved)
                loaded = yt.load_config()
                self.assertEqual(loaded.get("tag_harness"), "agy")
                self.assertEqual(loaded.get("tag_model"), "gemini-3.8-flash-high")

                # Environment overrides config
                with patch.dict(yt.os.environ, {"YT2MD_TAG_HARNESS": "claude"}):
                    env_loaded = yt.load_config()
                    self.assertEqual(env_loaded.get("tag_harness"), "claude")

    def test_invalid_json_handling(self):
        import io
        import tempfile
        from contextlib import redirect_stderr
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_file = Path(tmpdir) / "config.json"
            cfg_file.write_text("{ broken json content", encoding="utf-8")
            cfg_dir = Path(tmpdir)
            with patch.object(yt, "CONFIG_FILE", cfg_file), \
                 patch.object(yt, "CONFIG_DIR", cfg_dir), \
                 patch.dict(yt.os.environ, {}, clear=True):
                err_buf = io.StringIO()
                with redirect_stderr(err_buf):
                    # load_config gracefully returns empty dict
                    self.assertEqual(yt.load_config(), {})
                    # save_config refuses to overwrite damaged file
                    saved = yt.save_config({"tag_harness": "claude"})
                    self.assertFalse(saved)

                # File content preserved
                self.assertEqual(cfg_file.read_text(encoding="utf-8"), "{ broken json content")
                self.assertIn("failed to read config file", err_buf.getvalue())
                self.assertIn("refusing to overwrite", err_buf.getvalue())

    def test_non_dict_json_handling(self):
        import io
        import tempfile
        from contextlib import redirect_stderr
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_file = Path(tmpdir) / "config.json"
            cfg_file.write_text('["not", "a", "dict"]\n', encoding="utf-8")
            cfg_dir = Path(tmpdir)
            with patch.object(yt, "CONFIG_FILE", cfg_file), \
                 patch.object(yt, "CONFIG_DIR", cfg_dir), \
                 patch.dict(yt.os.environ, {}, clear=True):
                err_buf = io.StringIO()
                with redirect_stderr(err_buf):
                    self.assertEqual(yt.load_config(), {})
                    saved = yt.save_config({"tag_harness": "claude"})
                    self.assertFalse(saved)

                self.assertEqual(cfg_file.read_text(encoding="utf-8"), '["not", "a", "dict"]\n')
                self.assertIn("does not contain a JSON object", err_buf.getvalue())

    def test_config_aliases(self):
        import tempfile
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_file = Path(tmpdir) / "config.json"
            cfg_file.write_text(json.dumps({"harness": "codex", "model": "gpt-4o"}), encoding="utf-8")
            cfg_dir = Path(tmpdir)
            with patch.object(yt, "CONFIG_FILE", cfg_file), \
                 patch.object(yt, "CONFIG_DIR", cfg_dir), \
                 patch.dict(yt.os.environ, {}, clear=True):
                loaded = yt.load_config()
                self.assertEqual(loaded.get("tag_harness"), "codex")
                self.assertEqual(loaded.get("tag_model"), "gpt-4o")

    def test_env_overrides_model_and_tagger(self):
        import tempfile
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_file = Path(tmpdir) / "config.json"
            cfg_file.write_text(json.dumps({
                "tag_harness": "agy",
                "tag_model": "gemini-3.8-flash-high",
                "tagger": "default_tagger"
            }), encoding="utf-8")
            cfg_dir = Path(tmpdir)
            with patch.object(yt, "CONFIG_FILE", cfg_file), \
                 patch.object(yt, "CONFIG_DIR", cfg_dir), \
                 patch.dict(yt.os.environ, {
                     "YT2MD_TAG_HARNESS": "gemini",
                     "YT2MD_TAG_MODEL": "gemini-1.5-flash",
                     "YT2MD_TAGGER": "custom_tagger"
                 }, clear=True):
                loaded = yt.load_config()
                self.assertEqual(loaded.get("tag_harness"), "gemini")
                self.assertEqual(loaded.get("tag_model"), "gemini-1.5-flash")
                self.assertEqual(loaded.get("tagger"), "custom_tagger")


class CliConfigCommands(unittest.TestCase):
    def test_show_config(self):
        import io
        import tempfile
        from contextlib import redirect_stdout
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_file = Path(tmpdir) / "config.json"
            cfg_dir = Path(tmpdir)
            with patch.object(yt, "CONFIG_FILE", cfg_file), \
                 patch.object(yt, "CONFIG_DIR", cfg_dir), \
                 patch.dict(yt.os.environ, {}, clear=True):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = yt.main(["--show-config"])
                self.assertEqual(rc, 0)
                out = buf.getvalue()
                self.assertIn("Effective settings:", out)
                self.assertIn("tag_harness: agy", out)
                self.assertIn("tag_model:   gemini-3.8-flash-high", out)

    def test_set_harness_and_model_with_normalization(self):
        import io
        import tempfile
        from contextlib import redirect_stdout
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_file = Path(tmpdir) / "config.json"
            cfg_dir = Path(tmpdir)
            with patch.object(yt, "CONFIG_FILE", cfg_file), \
                 patch.object(yt, "CONFIG_DIR", cfg_dir), \
                 patch.dict(yt.os.environ, {}, clear=True):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = yt.main(["--set-harness", "agy", "--set-model", "gemini-3.8-flash"])
                self.assertEqual(rc, 0)
                data = json.loads(cfg_file.read_text(encoding="utf-8"))
                self.assertEqual(data.get("tag_harness"), "agy")
                self.assertEqual(data.get("tag_model"), "gemini-3.8-flash-high")

    def test_set_harness_refuses_corrupted_config(self):
        import io
        import tempfile
        from contextlib import redirect_stderr
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_file = Path(tmpdir) / "config.json"
            cfg_file.write_text("{ corrupt", encoding="utf-8")
            cfg_dir = Path(tmpdir)
            with patch.object(yt, "CONFIG_FILE", cfg_file), \
                 patch.object(yt, "CONFIG_DIR", cfg_dir), \
                 patch.dict(yt.os.environ, {}, clear=True):
                err_buf = io.StringIO()
                with redirect_stderr(err_buf):
                    rc = yt.main(["--set-harness", "claude"])
                self.assertEqual(rc, 1)
                self.assertEqual(cfg_file.read_text(encoding="utf-8"), "{ corrupt")
                self.assertIn("refusing to overwrite", err_buf.getvalue())

    def test_unknown_harness_in_config_fallback(self):
        import io
        import tempfile
        from contextlib import redirect_stdout, redirect_stderr
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_file = Path(tmpdir) / "config.json"
            cfg_file.write_text(json.dumps({"tag_harness": "unknown_harness"}), encoding="utf-8")
            cfg_dir = Path(tmpdir)
            with patch.object(yt, "CONFIG_FILE", cfg_file), \
                 patch.object(yt, "CONFIG_DIR", cfg_dir), \
                 patch.dict(yt.os.environ, {}, clear=True):
                out_buf, err_buf = io.StringIO(), io.StringIO()
                with redirect_stdout(out_buf), redirect_stderr(err_buf):
                    rc = yt.main(["--show-config"])
                self.assertEqual(rc, 0)
                self.assertIn("warning: unknown harness 'unknown_harness'", err_buf.getvalue())
                self.assertIn("tag_harness: agy", out_buf.getvalue())

    def test_quiet_suppresses_config_warning(self):
        import io
        import tempfile
        from contextlib import redirect_stdout, redirect_stderr
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_file = Path(tmpdir) / "config.json"
            cfg_file.write_text("{ corrupt json", encoding="utf-8")
            cfg_dir = Path(tmpdir)
            with patch.object(yt, "CONFIG_FILE", cfg_file), \
                 patch.object(yt, "CONFIG_DIR", cfg_dir), \
                 patch.dict(yt.os.environ, {}, clear=True):
                out_buf, err_buf = io.StringIO(), io.StringIO()
                with redirect_stdout(out_buf), redirect_stderr(err_buf):
                    rc = yt.main(["-q", "--show-config"])
                self.assertEqual(rc, 0)
                self.assertEqual(err_buf.getvalue(), "")


class Run(unittest.TestCase):
    def test_timeout_kills_grandchildren_holding_the_pipes(self):
        import time
        t = time.perf_counter()
        with self.assertRaises(yt.subprocess.TimeoutExpired):
            yt.run(["sh", "-c", "sleep 30 & sleep 30"], timeout=0.3)
        self.assertLess(time.perf_counter() - t, 5)

    def test_stdin_is_closed_without_input(self):
        r = yt.run(["cat"], timeout=5)
        self.assertEqual(r.stdout, "")


class SuggestTagsTimeout(unittest.TestCase):
    def setUp(self):
        import tempfile
        from unittest.mock import patch
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        for p in (patch.object(yt, "QUIET", True),
                  patch.object(yt, "TAG_VOCAB", self.tmp / "tags.txt")):
            p.start()
            self.addCleanup(p.stop)

    def test_hanging_tagger_is_skipped_after_retries(self):
        from unittest.mock import patch
        with patch.object(yt, "run", side_effect=yt.subprocess.TimeoutExpired("claude", 0.2)) as run:
            tags = yt.suggest_tags("t", "c", "b", "claude", None, None, timeout=0.2)
        self.assertEqual(run.call_count, yt.TAG_ATTEMPTS)
        self.assertEqual(tags, [])

    def test_retry_succeeds_on_second_attempt(self):
        from unittest.mock import patch
        success = yt.subprocess.CompletedProcess(["claude"], 0, "ai-tools", "")
        with patch.object(yt, "run", side_effect=[yt.subprocess.TimeoutExpired("claude", 0.5), success]) as run:
            tags = yt.suggest_tags("t", "c", "b", "claude", None, None, timeout=0.5)
        self.assertEqual(tags, ["ai-tools"])
        # The retry keeps the restricted flags, directory and environment.
        first, second = run.call_args_list
        self.assertEqual(first.args, second.args)
        self.assertEqual(first.kwargs, second.kwargs)
        self.assertIn("--safe-mode", second.args[0])
        self.assertTrue(Path(second.kwargs["cwd"]).name.startswith("yt2md-tags-"))
        self.assertNotIn("GH_TOKEN", second.kwargs["env"])

    def test_ctrl_c_skips_tags(self):
        from unittest.mock import patch
        with patch.object(yt, "run", side_effect=KeyboardInterrupt):
            self.assertEqual(yt.suggest_tags("t", "c", "b", "claude", None, None), [])


class TaggingSecurity(unittest.TestCase):
    def setUp(self):
        import tempfile
        from unittest.mock import patch
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for p in (patch.object(yt, "QUIET", True),
                  patch.object(yt, "TAG_VOCAB", Path(tmp.name) / "tags.txt")):
            p.start()
            self.addCleanup(p.stop)

    def test_unsupported_harness_and_custom_commands_never_launch(self):
        import io
        from contextlib import redirect_stderr
        from unittest.mock import patch
        err = io.StringIO()
        with patch.object(yt, "run") as run, redirect_stderr(err):
            for harness in ["agy", "codex", "opencode", "gemini"]:
                self.assertEqual(yt.suggest_tags("t", "c", "malicious instructions", harness, None, None), [])
            self.assertEqual(yt.suggest_tags("t", "c", "b", "claude", None, "sh -c malicious"), [])
        run.assert_not_called()
        # The skip changes the output, so it is reported even under --quiet.
        self.assertIn("tags skipped: gemini has no verified tool-free mode", err.getvalue())
        self.assertIn("tags skipped: custom tagger", err.getvalue())

    def test_skip_reason_only_allows_claude_and_ollama(self):
        self.assertIsNone(yt.tag_skip_reason("claude", None))
        self.assertIsNone(yt.tag_skip_reason("ollama", None))
        self.assertIsNotNone(yt.tag_skip_reason("claude", "llm -m x"))
        for harness in ["agy", "codex", "opencode", "gemini"]:
            self.assertIsNotNone(yt.tag_skip_reason(harness, None))

    def test_claude_has_no_tools_and_receives_only_auth_environment(self):
        from unittest.mock import patch
        with patch.dict(yt.os.environ, {"PATH": "/bin", "HOME": "/trusted-home",
                                        "GH_TOKEN": "unrelated", "ANTHROPIC_API_KEY": "test-auth"}, clear=True):
            def invoke(argv, **kwargs):
                self.assertEqual(argv[argv.index("--tools") + 1], "")
                self.assertIn("--safe-mode", argv)
                self.assertIn("--strict-mcp-config", argv)
                self.assertNotIn("GH_TOKEN", kwargs["env"])
                self.assertEqual(kwargs["env"]["ANTHROPIC_API_KEY"], "test-auth")
                self.assertNotEqual(Path(kwargs["cwd"]), Path.cwd())
                self.assertEqual(list(Path(kwargs["cwd"]).iterdir()), [])
                return yt.subprocess.CompletedProcess(argv, 0, "security-testing", "")
            with patch.object(yt, "run", side_effect=invoke):
                self.assertEqual(yt.suggest_tags("t", "c", "b", "claude", None, None), ["security-testing"])

    def test_ollama_runs_text_only_in_empty_directory_with_ollama_environment(self):
        from unittest.mock import patch
        with patch.dict(yt.os.environ, {"PATH": "/bin", "HOME": "/trusted-home", "GH_TOKEN": "unrelated",
                                        "ANTHROPIC_API_KEY": "other-provider",
                                        "OLLAMA_HOST": "http://127.0.0.1:11434"}, clear=True):
            def invoke(argv, **kwargs):
                self.assertEqual(argv, ["ollama", "run", "llama3.2"])
                self.assertIn("Title: t", kwargs["input"])
                self.assertEqual(kwargs["env"], {"PATH": "/bin", "HOME": "/trusted-home",
                                                 "OLLAMA_HOST": "http://127.0.0.1:11434"})
                self.assertNotEqual(Path(kwargs["cwd"]), Path.cwd())
                self.assertEqual(list(Path(kwargs["cwd"]).iterdir()), [])
                return yt.subprocess.CompletedProcess(argv, 0, "local-models", "")
            with patch.object(yt, "run", side_effect=invoke):
                self.assertEqual(yt.suggest_tags("t", "c", "b", "ollama", "llama3.2", None), ["local-models"])

    def test_environment_forwards_proxy_ca_and_claude_backends(self):
        from unittest.mock import patch
        forwarded = {
            "HTTPS_PROXY": "http://proxy:3128", "HTTP_PROXY": "http://proxy:3128", "NO_PROXY": "localhost",
            "https_proxy": "http://proxy:3128", "http_proxy": "http://proxy:3128", "no_proxy": "localhost",
            "NODE_EXTRA_CA_CERTS": "/etc/ca.pem", "SSL_CERT_FILE": "/etc/ssl.pem",
        }
        claude_only = {
            "CLAUDE_CONFIG_DIR": "/home/u/.claude-work",
            "CLAUDE_CODE_USE_BEDROCK": "1", "CLAUDE_CODE_USE_VERTEX": "1",
            "AWS_REGION": "us-east-1", "AWS_PROFILE": "work", "AWS_ACCESS_KEY_ID": "id",
            "AWS_SECRET_ACCESS_KEY": "secret", "AWS_SESSION_TOKEN": "session",
            "ANTHROPIC_VERTEX_PROJECT_ID": "project", "CLOUD_ML_REGION": "us-east5",
            "GOOGLE_APPLICATION_CREDENTIALS": "/home/u/gcp.json",
        }
        with patch.dict(yt.os.environ, {**forwarded, **claude_only, "GH_TOKEN": "unrelated"}, clear=True):
            self.assertEqual(yt.tagging_environment("claude"), {**forwarded, **claude_only})
            self.assertEqual(yt.tagging_environment("ollama"), forwarded)


class TagTimeoutValidation(unittest.TestCase):
    def test_invalid_config_values_are_rejected(self):
        from unittest.mock import patch
        for bad in (None, True, [1], 0, -5):
            with self.subTest(bad=bad), \
                 patch.object(yt, "load_config", return_value={"tag_timeout": bad}), \
                 patch("sys.stderr"), self.assertRaises(SystemExit):
                yt.main(["--no-tags", "https://youtu.be/x"])

    def test_invalid_flag_is_rejected(self):
        from unittest.mock import patch
        with patch("sys.stderr"), self.assertRaises(SystemExit):
            yt.main(["--tag-timeout", "0", "https://youtu.be/x"])



def frontmatter(doc):
    head, sep, rest = doc[len("---\n"):].partition("\n---\n\n")
    assert doc.startswith("---\n") and sep, doc
    return head.splitlines(), rest


FRONTMATTER_KEYS = ["source_url", "type", "title", "author", "captured_at",
                    "video_id", "subtitle_lang", "tags"]


class YtDlpInvocation(unittest.TestCase):
    def test_command_keeps_user_config_and_ends_options_before_url(self):
        cmd = yt.ytdlp_command("https://youtu.be/x", "firefox")
        self.assertEqual(cmd[0], "yt-dlp")
        self.assertNotIn("--ignore-config", cmd)
        self.assertEqual(cmd[-2:], ["--", "https://youtu.be/x"])
        self.assertLess(cmd.index("--cookies-from-browser"), cmd.index("--"))

    def test_bare_video_id_is_still_accepted(self):
        self.assertEqual(yt.ytdlp_command("zcLPGC-tvgk", None)[-2:], ["--", "zcLPGC-tvgk"])

    def test_video_id_starting_with_dash_is_accepted(self):
        self.assertEqual(yt.ytdlp_command("-wtIMTCHWuI", None)[-2:], ["--", "-wtIMTCHWuI"])
        self.assertEqual(yt.ytdlp_command("--abcdefghi", None)[-2:], ["--", "--abcdefghi"])

    def test_option_like_arguments_are_rejected(self):
        for bad in ["--cookies=/tmp/victim.txt", "-a/etc/passwd", " --plugin-dirs=x", "", "  ",
                    "--cookies=x", "-wtIMTCHWu", "-wtIMTCHWuIx", " -wtIMTCHWuI"]:
            with self.subTest(bad=bad), self.assertRaises(RuntimeError):
                yt.ytdlp_command(bad, None)

    def test_probe_rejects_option_without_running_ytdlp(self):
        from unittest.mock import patch
        with patch.object(yt, "run") as run, self.assertRaises(RuntimeError):
            yt.probe("--config-locations=/tmp/evil.conf", None)
        run.assert_not_called()

    def test_probe_runs_in_empty_temporary_directory(self):
        import os
        import tempfile
        from unittest.mock import patch
        seen = {}

        def invoke(cmd, **kwargs):
            seen["cmd"], seen["cwd"] = cmd, Path(kwargs["cwd"])
            seen["listing"] = list(seen["cwd"].iterdir())
            return yt.subprocess.CompletedProcess(cmd, 0, '{"id": "x"}', "")

        with tempfile.TemporaryDirectory() as work:
            # A hostile config in the directory the user runs yt2md from.
            Path(work, "yt-dlp.conf").write_text("--plugin-dirs .plugins\n")
            old = os.getcwd()
            os.chdir(work)
            try:
                with patch.object(yt, "run", side_effect=invoke):
                    self.assertEqual(yt.probe("https://youtu.be/x", None), {"id": "x"})
            finally:
                os.chdir(old)
            self.assertNotEqual(seen["cwd"].resolve(), Path(work).resolve())
        self.assertTrue(seen["cwd"].is_absolute())
        self.assertEqual(seen["listing"], [])
        self.assertFalse(seen["cwd"].exists())  # removed after the probe
        self.assertNotIn("--ignore-config", seen["cmd"])
        self.assertEqual(seen["cmd"][-2:], ["--", "https://youtu.be/x"])


class OutputFiles(unittest.TestCase):
    def setUp(self):
        import tempfile
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def test_existing_file_is_kept_and_suffix_added(self):
        (self.dir / "Talk.md").write_text("mine")
        first = yt.write_output(self.dir, "Talk", "new 1")
        second = yt.write_output(self.dir, "Talk", "new 2")
        self.assertEqual((self.dir / "Talk.md").read_text(), "mine")
        self.assertEqual(first.name, "Talk-2.md")
        self.assertEqual(second.name, "Talk-3.md")
        self.assertEqual(first.read_text(), "new 1")

    def test_overwrite_flag_restores_old_behavior(self):
        (self.dir / "Talk.md").write_text("old")
        dest = yt.write_output(self.dir, "Talk", "new", overwrite=True)
        self.assertEqual(dest, self.dir.resolve() / "Talk.md")
        self.assertEqual(dest.read_text(), "new")

    def test_same_video_is_replaced_atomically(self):
        import os
        doc = '---\nsource_url: "x"\nvideo_id: "abc-DEF_123"\n---\n\nold\n'
        (self.dir / "Talk.md").write_text(doc)
        before = os.stat(self.dir / "Talk.md").st_ino
        dest = yt.write_output(self.dir, "Talk", "new", video_id="abc-DEF_123")
        self.assertEqual(dest, self.dir.resolve() / "Talk.md")
        self.assertEqual(dest.read_text(), "new")
        self.assertNotEqual(os.stat(dest).st_ino, before)  # a new file, not truncated
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["Talk.md"])

    def test_same_video_in_older_unquoted_frontmatter_is_replaced(self):
        (self.dir / "Talk.md").write_text("---\ntitle: x\nvideo_id: abc\n---\nold\n")
        self.assertEqual(yt.write_output(self.dir, "Talk", "new", video_id="abc").name, "Talk.md")

    def test_same_video_saved_under_suffix_is_replaced(self):
        (self.dir / "Talk.md").write_text('---\nvideo_id: "other"\n---\n')
        (self.dir / "Talk-2.md").write_text('---\nvideo_id: "abc"\n---\nold\n')
        dest = yt.write_output(self.dir, "Talk", "new", video_id="abc")
        self.assertEqual(dest.name, "Talk-2.md")
        self.assertEqual(dest.read_text(), "new")
        self.assertFalse((self.dir / "Talk-3.md").exists())

    def test_other_video_or_no_frontmatter_gets_a_suffix(self):
        cases = {'---\nvideo_id: "other"\n---\n': "Talk-2.md",
                 "no frontmatter\nvideo_id: abc\n": "Talk-2.md",
                 '---\ntitle: x\n---\nvideo_id: "abc"\n': "Talk-2.md"}
        for content, expected in cases.items():
            with self.subTest(content=content):
                for p in self.dir.iterdir():
                    p.unlink()
                (self.dir / "Talk.md").write_text(content)
                self.assertEqual(yt.write_output(self.dir, "Talk", "new", video_id="abc").name,
                                 expected)
                self.assertEqual((self.dir / "Talk.md").read_text(), content)

    def test_symlink_to_same_video_is_not_replaced(self):
        outside = self.dir / "outside.md"
        outside.write_text('---\nvideo_id: "abc"\n---\nsecret\n')
        out = self.dir / "out"
        out.mkdir()
        (out / "Talk.md").symlink_to(outside)
        self.assertEqual(yt.write_output(out, "Talk", "x", video_id="abc").name, "Talk-2.md")
        self.assertTrue((out / "Talk.md").is_symlink())
        self.assertIn("secret", outside.read_text())

    @unittest.skipUnless(hasattr(__import__("os"), "mkfifo"), "needs mkfifo")
    def test_fifo_is_skipped_or_refused_without_blocking(self):
        import os
        os.mkfifo(self.dir / "Talk.md")
        self.assertEqual(yt.write_output(self.dir, "Talk", "x", video_id="abc").name, "Talk-2.md")
        with self.assertRaises(RuntimeError):
            yt.write_output(self.dir, "Talk", "x", overwrite=True)
        self.assertFalse([p for p in self.dir.iterdir() if p.name.endswith(".tmp")])

    def test_symlink_is_never_followed(self):
        outside = self.dir / "outside.txt"
        outside.write_text("secret")
        out = self.dir / "out"
        out.mkdir()
        (out / "Talk.md").symlink_to(outside)
        self.assertEqual(yt.write_output(out, "Talk", "x").name, "Talk-2.md")
        with self.assertRaises(RuntimeError):
            yt.write_output(out, "Talk", "x", overwrite=True)
        self.assertEqual(outside.read_text(), "secret")

    def test_path_is_absolute_and_inside_outdir(self):
        import os
        old = os.getcwd()
        os.chdir(self.dir)
        try:
            dest = yt.write_output("sub", "Talk", "x")
        finally:
            os.chdir(old)
        self.assertTrue(dest.is_absolute())
        self.assertEqual(dest.parent, (self.dir / "sub").resolve())

    def test_unsafe_names_are_refused(self):
        for stem in [".hidden", "a/../b"]:
            with self.subTest(stem=stem), self.assertRaises(RuntimeError):
                yt.write_output(self.dir, stem, "x")

    def test_reserved_and_hidden_titles_get_the_video_id(self):
        cases = {"CLAUDE": "CLAUDE-abc_12", "agents": "agents-abc_12", "Readme": "Readme-abc_12",
                 "CLAUDE.local": "CLAUDE.local-abc_12", "GEMINI.md": "GEMINI.md-abc_12",
                 "nul": "nul-abc_12", "Claude Code tips": "Claude Code tips",
                 "AGENT": "AGENT-abc_12", "crush": "crush-abc_12", "QWEN.md": "QWEN.md-abc_12",
                 "Warp": "Warp-abc_12", "CONIN$": "CONIN$-abc_12", "conout$": "conout$-abc_12",
                 "COM0": "COM0-abc_12", "lpt0": "lpt0-abc_12", "Warped": "Warped"}
        for title, stem in cases.items():
            with self.subTest(title=title):
                self.assertEqual(yt.output_stem(title, "abc_12"), stem)
        self.assertEqual(yt.output_stem("SKILL", "../x"), "SKILL-x")
        self.assertEqual(yt.output_stem("README", ""), "README-video")
        self.assertFalse(yt.output_stem("..bashrc", "id").startswith("."))


class ProcessWritesSafely(unittest.TestCase):
    """End to end through main(), with yt-dlp and the subtitle download mocked."""

    def setUp(self):
        import tempfile
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def run_main(self, info, *extra):
        import io
        from contextlib import redirect_stderr, redirect_stdout
        from unittest.mock import patch
        out, err = io.StringIO(), io.StringIO()
        sub = {"json3": [{"ext": "json3", "url": "https://www.youtube.com/api/timedtext?v=x"}]}
        info = {"subtitles": {"en": sub["json3"]}, "language": "en", **info}
        with patch.object(yt, "probe", return_value=info), \
             patch.object(yt, "fetch", return_value=track(cue(0, 1000, "hello"))), \
             patch.object(yt, "load_config", return_value={}), \
             redirect_stdout(out), redirect_stderr(err):
            rc = yt.main(["--no-tags", "-o", str(self.dir), *extra, "https://youtu.be/x"])
        return rc, out.getvalue(), err.getvalue()

    def test_title_cannot_replace_agent_instructions(self):
        (self.dir / "CLAUDE.md").write_text("project rules")
        rc, out, _ = self.run_main({"title": "CLAUDE", "id": "vid123"}, "--overwrite")
        self.assertEqual(rc, 0)
        self.assertEqual((self.dir / "CLAUDE.md").read_text(), "project rules")
        self.assertTrue((self.dir / "CLAUDE-vid123.md").exists())
        self.assertIn(str(self.dir.resolve() / "CLAUDE-vid123.md"), out)

    def test_second_run_of_same_video_updates_the_file(self):
        self.run_main({"title": "Talk", "id": "v"})
        first = (self.dir / "Talk.md").read_text()
        (self.dir / "Talk.md").write_text(first.replace("hello", "stale"))
        rc, out, _ = self.run_main({"title": "Talk", "id": "v"})
        self.assertEqual(rc, 0)
        self.assertEqual([p.name for p in self.dir.iterdir()], ["Talk.md"])
        self.assertIn("hello", (self.dir / "Talk.md").read_text())
        self.assertIn(str(self.dir.resolve() / "Talk.md"), out)

    def test_run_of_another_video_with_same_title_keeps_first_file(self):
        self.run_main({"title": "Talk", "id": "v1"})
        first = (self.dir / "Talk.md").read_text()
        self.run_main({"title": "Talk", "id": "v2"})
        self.assertEqual((self.dir / "Talk.md").read_text(), first)
        self.assertIn('video_id: "v2"', (self.dir / "Talk-2.md").read_text())

    def test_hand_written_file_is_kept(self):
        (self.dir / "Talk.md").write_text("edited by hand")
        self.run_main({"title": "Talk", "id": "v"})
        self.assertEqual((self.dir / "Talk.md").read_text(), "edited by hand")
        self.assertTrue((self.dir / "Talk-2.md").exists())

    def test_video_id_starting_with_dash_runs_after_double_dash(self):
        import io
        from contextlib import redirect_stderr, redirect_stdout
        from unittest.mock import patch
        sub = [{"ext": "json3", "url": "https://www.youtube.com/api/timedtext?v=x"}]
        info = {"subtitles": {"en": sub}, "language": "en", "title": "Dash", "id": "-wtIMTCHWuI"}
        seen = []

        def invoke(cmd, **kwargs):
            seen.append(cmd)
            return yt.subprocess.CompletedProcess(cmd, 0, json.dumps(info), "")

        out, err = io.StringIO(), io.StringIO()
        with patch.object(yt, "run", side_effect=invoke), \
             patch.object(yt, "fetch", return_value=track(cue(0, 1000, "hello"))), \
             patch.object(yt, "load_config", return_value={}), \
             redirect_stdout(out), redirect_stderr(err):
            rc = yt.main(["--no-tags", "-o", str(self.dir), "--", "-wtIMTCHWuI"])
        self.assertEqual(rc, 0, err.getvalue())
        self.assertEqual(seen[0][-2:], ["--", "-wtIMTCHWuI"])
        self.assertTrue((self.dir / "Dash.md").exists())

    def test_terminal_escapes_never_reach_stderr_file_name_or_markdown(self):
        title = "T\x1b]0;PWNED-TITLE\x07\x1b[31mRED\r\nnext‮"
        rc, out, err = self.run_main({"title": title, "uploader": "C\x1b[2J", "id": "v"})
        self.assertEqual(rc, 0)
        files = list(self.dir.iterdir())
        self.assertEqual([f.name for f in files], ["TRED next.md"])
        doc = files[0].read_text()
        for text in (err, out, doc):
            self.assertNotIn("\x1b", text)
            self.assertNotIn("\x07", text)
            self.assertNotIn("‮", text)
        self.assertIn("# TRED next\n", doc)

    def test_option_like_url_fails_cleanly(self):
        import io
        from contextlib import redirect_stderr
        from unittest.mock import patch
        err = io.StringIO()
        with patch.object(yt, "run") as run, patch.object(yt, "load_config", return_value={}), \
             redirect_stderr(err):
            rc = yt.main(["--no-tags", "-o", str(self.dir), "--", "--cookies=/tmp/x.txt"])
        self.assertEqual(rc, 1)
        run.assert_not_called()
        self.assertIn("not a URL or video ID", err.getvalue())


class SubtitleFetch(unittest.TestCase):
    def test_file_url_is_refused_without_reading(self):
        import tempfile
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as d:
            secret = Path(d) / "notes.json3"
            secret.write_text(track(cue(0, 1000, "local secret")))
            with patch.object(yt.urllib.request, "build_opener") as opener, \
                 self.assertRaises(RuntimeError) as ctx:
                yt.fetch(secret.as_uri())
            opener.assert_not_called()
        self.assertIn("only https://", str(ctx.exception))

    def test_only_public_https_hosts_are_accepted(self):
        refused = ["http://www.youtube.com/api/timedtext", "ftp://example.com/x",
                   "data:text/plain,hi", "https://localhost/x", "https://a.localhost/x",
                   "https://127.0.0.1/x", "https://[::1]/x", "https://169.254.169.254/latest",
                   "https://10.0.0.5/x", "https://192.168.1.1/x", "https://[::ffff:127.0.0.1]/x",
                   "https:///nohost", "not a url",
                   # Numeric IPv4 forms the C resolver accepts.
                   "https://2130706433/x", "https://0x7f000001/x", "https://127.1/x",
                   "https://0177.0.0.1/x", "https://0x7f.1/x", "https://10.1/x",
                   "https://3232235777/x", "https://1.2.3.4.5/x",
                   # NAT64 with an embedded loopback or private address.
                   "https://[64:ff9b::7f00:1]/x", "https://[64:ff9b::10.0.0.1]/x",
                   "https://[fe80::1%25eth0]/x"]
        for url in refused:
            with self.subTest(url=url), self.assertRaises(RuntimeError):
                yt.check_subtitle_url(url)
        for url in ["https://www.youtube.com/api/timedtext?v=x&fmt=json3",
                    "https://8.8.8.8/x", "https://134744072/x", "https://[64:ff9b::8.8.8.8]/x",
                    "https://deadbeef.example/x", "https://1e100.net/x", "https://0x.example/x"]:
            self.assertEqual(yt.check_subtitle_url(url), url)

    def test_redirect_to_internal_address_is_refused(self):
        handler = yt._CheckedRedirect()
        req = yt.urllib.request.Request("https://www.youtube.com/a")
        with self.assertRaises(RuntimeError):
            handler.redirect_request(req, None, 302, "Found", {},
                                     "http://169.254.169.254/latest/meta-data")

    def test_body_size_is_limited(self):
        import io

        class Resp(io.BytesIO):
            def __init__(self, data, length=None):
                super().__init__(data)
                self.headers = {"Content-Length": length} if length else {}

        self.assertEqual(yt.read_limited(Resp(b"abc"), limit=3), b"abc")
        with self.assertRaises(RuntimeError):
            yt.read_limited(Resp(b"abcd"), limit=3)
        with self.assertRaises(RuntimeError):
            yt.read_limited(Resp(b"", length="999999999999"), limit=3)

    def test_retry_after_is_bounded(self):
        self.assertEqual(yt.retry_after({"Retry-After": "5"}, 2.0), 5.0)
        self.assertEqual(yt.retry_after({"Retry-After": "1e9"}, 2.0), yt.MAX_RETRY_AFTER)
        for bad in ["inf", "nan", "-3", "0", "Wed, 21 Oct 2015 07:28:00 GMT", "x" * 10000, ""]:
            with self.subTest(bad=bad[:20]):
                self.assertEqual(yt.retry_after({"Retry-After": bad}, 2.0), 2.0)
        self.assertEqual(yt.retry_after(None, 4.0), 4.0)

    def test_fetch_waits_at_most_the_cap(self):
        import io
        from email.message import Message
        from unittest.mock import MagicMock, patch
        headers = Message()
        headers["Retry-After"] = "1000000000"
        busy = yt.urllib.error.HTTPError("https://www.youtube.com/a", 429, "busy", headers, None)
        self.addCleanup(busy.close)
        resp = MagicMock()
        resp.__enter__.return_value = resp
        resp.headers = {}
        resp.read.side_effect = io.BytesIO(b'{"events": []}').read
        opener = MagicMock()
        opener.open.side_effect = [busy, resp]
        with patch.object(yt.urllib.request, "build_opener", return_value=opener), \
             patch.object(yt.time, "sleep") as sleep, patch.object(yt, "QUIET", True):
            self.assertEqual(yt.fetch("https://www.youtube.com/a"), '{"events": []}')
        self.assertLessEqual(sleep.call_args.args[0], yt.MAX_RETRY_AFTER + 1)


class FrontmatterInjection(unittest.TestCase):
    def test_metadata_cannot_add_keys_or_close_the_block(self):
        doc = yt.build_document('A "t"\n---\nreviewed: true', "C\nx: 1",
                                "abc\nreviewed: true", "en\ntags: [owned]",
                                ["ok-tag", "true", "123", "a, b"], "body")
        lines, rest = frontmatter(doc)
        self.assertEqual([l.split(":", 1)[0] for l in lines], FRONTMATTER_KEYS)
        values = {l.split(":", 1)[0]: l.split(": ", 1)[1] for l in lines}
        for key in ["source_url", "title", "author", "video_id", "subtitle_lang"]:
            self.assertTrue(values[key].startswith('"'), key)
        self.assertEqual(json.loads(values["video_id"]), "abc\nreviewed: true")
        self.assertEqual(json.loads(values["subtitle_lang"]), "en\ntags: [owned]")
        self.assertEqual(json.loads(values["title"]), 'A "t"\n---\nreviewed: true')
        self.assertEqual(values["tags"], '[ok-tag, "true", "123", "a, b"]')
        self.assertTrue(rest.startswith('# A "t" --- reviewed: true\n\n'))

    def test_frontmatter_round_trips_with_pyyaml(self):
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML not installed")
        doc = yt.build_document("t x\x85y\x7f", "c", "abc\nreviewed: true",
                                "en\ntags: [owned]", ["true", "a"], "b")
        data = yaml.safe_load(doc.split("\n---\n\n")[0][4:])
        self.assertEqual(set(data), set(FRONTMATTER_KEYS))
        self.assertEqual(data["video_id"], "abc\nreviewed: true")
        self.assertEqual(data["subtitle_lang"], "en\ntags: [owned]")
        self.assertEqual(data["title"], "t x\x85y\x7f")
        self.assertEqual(data["tags"], ["true", "a"])

    def test_yaml_str_escapes_line_breaks_and_controls(self):
        self.assertEqual(yt.yaml_str("a\nb\tc\x1b"), "a\\nb\\tc\\u001b")
        self.assertEqual(yt.yaml_str("x y\x85"), "x\\u2028y\\u0085")

    def test_clean_meta_strips_terminal_escapes(self):
        self.assertEqual(yt.clean_meta("T\x1b]0;PWNED\x07\x1b[31mRED\x1b[0m"), "TRED")
        self.assertEqual(yt.clean_meta("a\nb\r\x00c\x9b‮"), "a b c")
        self.assertEqual(yt.sanitize("x\x1b[31m\x07y"), "xy")


if __name__ == "__main__":
    unittest.main()
