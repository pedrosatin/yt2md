# yt2md

Turn a YouTube video into a clean Markdown transcript, ready for a knowledge base.

Criado por [@pedrosatin](https://github.com/pedrosatin)

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
OK /home/you/videos/LIVE Uncle Bob on Software Fundamentals in the Age of AI.md
```

The result is a `<video title>.md` file (see [Output files](#output-files) for
what happens when that name is taken):

```markdown
---
source_url: "https://www.youtube.com/watch?v=zcLPGC-tvgk"
type: video
title: "LIVE: Uncle Bob on Software Fundamentals in the Age of AI"
author: "Matt Pocock"
captured_at: 2026-09-07T20:44:27+00:00
video_id: "zcLPGC-tvgk"
subtitle_lang: "en"
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
| `claude` or `ollama` | optional | Only for `tags:`. Skip it with `--no-tags`. |

Tagging CLIs, via `--tag-harness`:

| Harness | Invocation used | Tags |
|---|---|---|
| `claude` | `claude --safe-mode --tools "" --strict-mcp-config --mcp-config '{"mcpServers":{}}' --disable-slash-commands --no-session-persistence -p --model haiku` | generated |
| `ollama` | `ollama run <model>` | generated |
| `agy` (default) | not launched | skipped |
| `codex` | not launched | skipped |
| `gemini` | not launched | skipped |
| `opencode` | not launched | skipped |
| `--tagger` command | not launched | skipped |

Only Claude and Ollama run, because only they can be started without tools.
See [Tool-free tagging](#tool-free-tagging) for the reason and for what the
CLI receives.

## Setup

### 1. Install yt-dlp

The only hard dependency. Pick whichever fits your system:

```bash
sudo pacman -S yt-dlp          # Arch
sudo apt install yt-dlp        # Debian / Ubuntu
brew install yt-dlp            # macOS
pipx install yt-dlp            # anywhere with Python
```

Check it:

```bash
yt-dlp --version
python3 --version              # needs 3.9 or newer
```

### 2. Get the script

The whole tool is a single file, so downloading it is enough:

```bash
mkdir -p ~/.local/bin
curl -fsSL -o ~/.local/bin/yt2md https://raw.githubusercontent.com/pedrosatin/yt2md/main/yt2md
chmod +x ~/.local/bin/yt2md
```

To update later, run the same `curl` again.

<details>
<summary>Alternative: clone and symlink</summary>

Better if you plan to edit the script or follow its history - `git pull` then
updates the command with no reinstall step:

```bash
git clone https://github.com/pedrosatin/yt2md.git ~/Work/yt2md
chmod +x ~/Work/yt2md/yt2md
mkdir -p ~/.local/bin
ln -sf ~/Work/yt2md/yt2md ~/.local/bin/yt2md
```

</details>

### 3. Put `~/.local/bin` on your PATH

Skip this if `echo $PATH` already contains it.

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc   # or ~/.zshrc
exec $SHELL
```

### 4. Verify

```bash
command -v yt2md                              # -> ~/.local/bin/yt2md
yt2md --help
yt2md https://youtu.be/jNQXAC9IVRw --stdout --no-tags | head
```

The last command is a 19-second video and exercises the whole pipeline without
touching an LLM. If it prints Markdown, the setup is done.

### 5. Tagging (optional)

`tags:` needs `claude` or `ollama` on your `PATH`. The default harness is still
`agy`, and with it tags are skipped: yt2md prints a warning and saves the file
with `tags: []`. Pick a harness that generates tags:

```bash
claude --version
yt2md --set-harness claude     # or: yt2md --set-harness ollama --set-model llama3.2
yt2md <url> -o ~/videos
```

Or turn tagging off with `--no-tags`.

#### Changing the default agent

You can change the default agent in any of these ways. Only `claude` and
`ollama` generate tags; the other names are accepted, but tagging is skipped
with them.

1. **Persistently via CLI:**
   ```bash
   yt2md --set-harness claude                     # switch default harness to claude
   yt2md --set-harness ollama --set-model llama3.2
   yt2md --show-config                            # inspect current effective defaults
   ```

2. **Via config file (`~/.config/yt2md/config.json`):**
   ```json
   {
     "tag_harness": "claude",
     "tag_model": "haiku",
     "tag_timeout": 60
   }
   ```

3. **Via environment variables:**
   ```bash
   export YT2MD_TAG_HARNESS=claude
   export YT2MD_TAG_MODEL=haiku
   ```

4. **Per invocation:**
   ```bash
   yt2md <url> --tag-harness claude
   yt2md <url> --tag-harness ollama --tag-model llama3.2
   ```

No LLM CLI at all? Use `--no-tags` and the file is written with `tags: []`.
A tagging failure never loses the transcript - it warns and saves anyway.
The warning for a skipped harness is printed even with `-q`.
A tagger that hangs is killed after `--tag-timeout` seconds (60 by default) and
retried once. Ctrl+C during tagging skips the tags for that video and still
saves the file.

## Usage

```
yt2md <url> [<url>...] [options]

  -l, --lang LANG           force a language (default: the video's original)
  -o, --outdir DIR          output directory (default: cwd)
      --stdout              print instead of saving
      --overwrite           always replace <title>.md instead of adding -2, -3...
      --keep-timestamps     keep the timestamps
      --keep-sound-tags     keep [Laughter], [Applause], music notes
  -q, --quiet               do not print step progress
      --no-tags             skip tag generation (avoids the LLM call)
      --tag-harness NAME    claude | ollama generate tags; agy | codex | gemini | opencode skip them
      --tag-model MODEL     model for tagging
      --tagger COMMAND      custom tagging command; tagging is skipped when set
      --tag-timeout SECONDS seconds per tagging attempt (default: 60, 2 attempts)
      --cookies-from-browser BROWSER
      --show-config         show current defaults and available harnesses
      --set-harness NAME    persistently save default harness to config.json
      --set-model MODEL     persistently save default model to config.json
```

Progress goes to stderr, so `--stdout` stays pipeable:

```bash
yt2md <url> --stdout --no-tags | less
```

yt2md passes each URL to yt-dlp after yt-dlp's own `--`, so it is never read as
an option. Any URL argument that starts with `-` is rejected before yt-dlp
starts, unless it is an 11-character video ID. A bare video ID such as
`zcLPGC-tvgk` works. For an ID that starts with `-`, put yt2md's `--` before
it so its own option parser accepts it: `yt2md -- -wtIMTCHWuI`.

## Output files

The file is named after the video title, and yt2md only replaces a file it
wrote for the same video:

- If `<title>.md` exists and its frontmatter has the same `video_id`, running
  yt2md again on that video updates it. The new file is written next to it and
  then moved into place, so a failed run leaves the old one intact.
- If `<title>.md` belongs to another video or was not written by yt2md, the
  transcript is saved as `<title>-2.md`, then `<title>-3.md`, and so on. A
  `-2`, `-3` file of the same video is updated the same way.
- Pass `--overwrite` to always replace `<title>.md`. A symlink, FIFO or other
  non-regular file at that path is never written through: without
  `--overwrite` the next free name is used, and with it the write fails.
- The name is cut to 200 bytes of UTF-8 before `-2` and `.md`, without
  splitting a character, so long titles in Japanese or full of emoji still fit
  the 255-byte limit of most file systems.
- Titles that would produce a file other tools read as instructions or project
  metadata get the video ID appended. The reserved names are `AGENTS`, `AGENT`,
  `CLAUDE`, `GEMINI`, `COPILOT-INSTRUCTIONS`, `CONVENTIONS`, `CRUSH`, `QWEN`,
  `WARP`, `SKILL`, `README`, `CONTRIBUTING`, `SECURITY`, `CHANGELOG`, `LICENSE`,
  `CODE_OF_CONDUCT` and the Windows device names `CON`, `PRN`, `AUX`, `NUL`,
  `CONIN$`, `CONOUT$`, `COM0` to `COM9` and `LPT0` to `LPT9`. Any case counts,
  and so does a name followed by a dot, such as `CLAUDE.local`. `CLAUDE` becomes,
  for example, `CLAUDE-zcLPGC-tvgk.md`. This applies with `--overwrite` too.
- The name never starts with `.`, never contains `/` or `\`, and the file is
  always created directly inside the output directory. The path printed after
  `OK` is absolute.
- Escape sequences and control characters in the title and channel are removed
  before they reach the terminal, the file name or the Markdown. In the
  frontmatter every text value is a quoted YAML string, so metadata cannot add
  keys or close the block early.

## Network and yt-dlp

yt2md runs yt-dlp from an empty temporary directory, so a `yt-dlp.conf` or a
plugin folder in the directory you run yt2md from is never read. Such a file
could otherwise load plugins and run code when you use yt2md inside a downloaded
folder or a cloned repository. Your own `~/.config/yt-dlp/config` and the system
config are still read, so settings such as a proxy or extractor arguments keep
working.

The subtitle track is downloaded only from an `https://` URL. `file://`,
`http://` and other schemes are refused. The host in the URL is checked, also
after each redirect: `localhost` and names ending in `.localhost` are refused,
and so is an IP address outside the public ranges (loopback, private,
link-local and similar). That covers IPv4 written as a number or in
octal or hex (`2130706433`, `0x7f000001`, `127.1`, `0177.0.0.1`), IPv4-mapped
IPv6 and NAT64 addresses (`64:ff9b::/96`). Host names are not resolved, so a
name that points at an internal address is not caught by this check; the
`https://` certificate check still has to pass for that name. The download is
capped at 32 MiB, and a `Retry-After` header is honored for at most 60 seconds.

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

## Tool-free tagging

Tagging sends the video title, channel and transcript to an LLM CLI. That text
comes from third parties, so it could contain instructions aimed at the model.
yt2md only launches a CLI that cannot act on them: one started without tools,
file access or commands.

- Claude runs with `--safe-mode` (no CLAUDE.md, skills, plugins or hooks), an
  empty tools list, an empty strict MCP configuration, slash commands disabled
  and no session saved.
- Ollama's `ollama run` only generates text.
- agy, Codex, Gemini, OpenCode and `--tagger` commands are not launched. None of
  them has a mode where tools and startup hooks can be turned off with
  certainty. Gemini, for example, still runs global hooks and extensions when
  tools are denied.

Your configured harness is not changed; if it is not Claude or Ollama, tags are
skipped and the transcript is saved with `tags: []`.

The CLI runs in an empty temporary directory and gets a reduced environment:
`PATH`, `HOME`, `USER`, `LANG`, `LC_ALL`, `TMPDIR`, the proxy variables
(`HTTPS_PROXY`, `HTTP_PROXY`, `NO_PROXY`, upper or lower case), the CA
variables (`SSL_CERT_FILE`, `SSL_CERT_DIR`, `NODE_EXTRA_CA_CERTS`), plus the
selected provider's settings:

- Claude: `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `CLAUDE_CODE_OAUTH_TOKEN`,
  `ANTHROPIC_BASE_URL`, `CLAUDE_CONFIG_DIR`, and the Bedrock and Vertex
  variables (`CLAUDE_CODE_USE_BEDROCK`, `CLAUDE_CODE_USE_VERTEX`, `AWS_REGION`,
  `AWS_PROFILE`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`,
  `AWS_SESSION_TOKEN`, `ANTHROPIC_VERTEX_PROJECT_ID`, `CLOUD_ML_REGION`,
  `GOOGLE_APPLICATION_CREDENTIALS`).
- Ollama: `OLLAMA_HOST`, `OLLAMA_API_KEY`.

Everything else, such as tokens for other services, is dropped.

If your Claude CLI is too old to accept these flags, tagging is skipped; yt2md
never retries without them.

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

82 offline tests, no network and no LLM.

## Contributing

Contributions and bug reports are welcome. Open an issue at
[https://github.com/pedrosatin/yt2md/issues](https://github.com/pedrosatin/yt2md/issues)
to propose a change or report a problem.

## License

MIT
