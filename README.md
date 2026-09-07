# yt2md

Turn a YouTube video into a clean Markdown transcript, ready for a knowledge base.

```bash
yt2md https://youtu.be/zcLPGC-tvgk -o ~/videos
```

```
-> https://youtu.be/zcLPGC-tvgk
  1/4 fetching metadata...
      LIVE: Uncle Bob on Software Fundamentals in the Age of AI - Matt Pocock (4.8s)
  2/4 downloading 'en' subtitles...
      1449 cues (0.5s)
  3/4 assembling paragraphs...
      141 paragraphs, 9987 words
  4/4 generating tags via claude (haiku)...
      ai-agents, code-quality, software-architecture, clean-code (14.2s)
OK LIVE Uncle Bob on Software Fundamentals in the Age of AI.md
```

The result is a `<video title>.md` file:

```markdown
---
source_url: "https://www.youtube.com/watch?v=zcLPGC-tvgk"
type: video
title: "LIVE: Uncle Bob on Software Fundamentals in the Age of AI"
author: "Matt Pocock"
captured_at: 2026-09-07T20:44:27+00:00
video_id: zcLPGC-tvgk
subtitle_lang: en
tags: [ai-agents, code-quality, software-architecture, clean-code]
---

# LIVE: Uncle Bob on Software Fundamentals in the Age of AI

I've got a treat for you today. I've got someone who I've been wanting to
speak to for a while...
```

## Dependencies

| | Required | Notes |
|---|---|---|
| **Python 3.9+** | yes | Standard library only - nothing to `pip install`. |
| **[yt-dlp](https://github.com/yt-dlp/yt-dlp)** | yes | Must be on `PATH`. It is itself a Python program, so Python is already a transitive dependency. |
| An LLM CLI | optional | Only for `tags:`. Skip it with `--no-tags`. |

Supported tagging CLIs, via `--tag-harness`:

| Harness | Invocation used | Status |
|---|---|---|
| `claude` (default) | `claude -p --model haiku` | tested |
| `codex` | `codex exec --skip-git-repo-check -` | tested |
| `opencode` | `opencode run` | tested |
| `gemini` | `gemini --skip-trust -p <prompt>` | untested (blocked on tier eligibility) |
| `ollama` | `ollama run <model>` | untested |

Anything else works through `--tagger`, which receives the prompt on stdin:

```bash
yt2md <url> --tagger "llm -m gpt-4o-mini"
```

## Install

```bash
curl -o ~/.local/bin/yt2md https://raw.githubusercontent.com/pedrosatin/yt2md/main/yt2md
chmod +x ~/.local/bin/yt2md
```

## Usage

```
yt2md <url> [<url>...] [options]

  -l, --lang LANG           force a language (default: the video's original)
  -o, --outdir DIR          output directory (default: cwd)
      --stdout              print instead of saving
      --keep-timestamps     keep the timestamps
      --keep-sound-tags     keep [Laughter], [Applause], music notes
  -q, --quiet               do not print step progress
      --no-tags             skip tag generation (avoids the LLM call)
      --tag-harness NAME    claude | codex | opencode | gemini | ollama
      --tag-model MODEL     model for tagging
      --tagger COMMAND      custom tagging command, prompt on stdin
      --cookies-from-browser BROWSER
```

Progress goes to stderr, so `--stdout` stays pipeable:

```bash
yt2md <url> --stdout --no-tags | less
```

## What it handles

Four things about YouTube's subtitle data that are easy to get wrong:

**Auto-caption duplication.** Auto-generated captions have a rolling effect that
repeats every line. In the `json3` format those repeats are flagged `aAppend`, so
they can be dropped. On a 56-minute talk that is 1453 of 2908 events - half the
file is duplication. A `.vtt`-based pipeline keeps all of it.

**Machine translations.** Asking for a language other than the original makes
YouTube generate a translation on demand: slow, aggressively rate-limited, and
the usual cause of `HTTP 429`. It is also worse text - "I have a surprise for you
today" where the speaker said "I've got a treat for you today". Translated tracks
carry `tlang=` in their URL, which is the reliable way to spot them.

**`*-orig` is not a reliable "original" marker.** On a video with dubbed audio
tracks, YouTube emits one `-orig` key per dub - 21 of them on the video above.
Only a single `-orig` identifies the original language.

**Paragraphs need durations.** Breaks are inferred from real silence between
cues, which requires `dDurationMs`, not just `tStartMs`. Measuring the distance
between consecutive cue *starts* instead splits sentences mid-phrase.

Closed-caption artifacts are stripped: `[laughter]`, `(APPLAUSE)`, music notes,
and the `>>` speaker markers - the latter become paragraph breaks, and a
`NAME:` prefix becomes `**NAME:**`.

## Tag vocabulary

Tags accumulate in `~/.config/yt2md/tags.txt`, and every previously used tag is
fed to the model on the next run with an instruction to reuse rather than invent
a synonym. Without this you end up with `tdd`, `test-driven-development` and
`testing` as three separate tags, which defeats the point of tagging at all.

The vocabulary is a plain text file - edit it freely.

## Knowledge base

The frontmatter matches what [graphify](https://github.com/safishamsi/graphify) reads: it
copies `source_url`, `captured_at` and `author` onto every node extracted from
the file. Because only the body below the `---` is hashed for its cache, editing
frontmatter afterwards (fixing a tag, marking something reviewed) does not
trigger a re-extraction.

Suggested flow: keep every transcript in one flat folder and let clustering do
the grouping, rather than maintaining a folder tree by hand.

## Known limitation

Auto-generated captions arrive **without punctuation**. The paragraphs this tool
builds come from speech pauses and help readability, but they are not a
substitute for real punctuation. Whisper-based transcription solves that at the
cost of minutes per video instead of seconds.

## Tests

```bash
python3 -m unittest -v test_yt2md
```

27 offline tests, no network and no LLM.

## License

MIT
