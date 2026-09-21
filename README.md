# siw-charting

An MCP server over a nursing documentation guide: **57 articles built on
121 published court decisions**, free, with every decision linked.

Ask it about a situation and it gives you the shape of the note.

```
draft_note("I got stuck with a needle after a patient")

  template    [DATE] [TIME]: During [PROCEDURE], care was paused due to
              staff sharps injury. Patient remained [CONDITION]...
  do not      "Dirty needle" · "Clean needle" · "Probably fine" · "No risk"
  behind it   Babich v. Waukesha Memorial, 1996
              Barrett v. Danbury Hospital, 1995
```

Every bracket is a fact **you** observed. The server writes the shape; it
cannot know what happened on your shift and does not pretend to.

## It takes no patient information

This is the part to read before anything else.

- **Nothing is stored.** No log file, no query history, no analytics.
- **No network connection is opened.** It reads one file from your disk.
- **Chart-shaped input is refused, not processed.** An MRN, a date of
  birth, a timed entry, or anything over 200 characters comes back with a
  refusal instead of an answer.

That is how the server is built. It is **not a compliance claim, and none
is offered**. If you point an assistant at a real patient's chart, what
governs that is your employer's policy and whether your model provider
has signed a business associate agreement — not a filter written by us.
A scrubber does not undo a disclosure that already happened.

Keep the patient out of the question and the question stays easy.

## Install

No packages, no build step. Python 3.9 or newer.

```sh
curl -O https://shiftiswild.com/notes/siw_charting.py
curl -O https://shiftiswild.com/notes/corpus.json
python3 siw_charting.py --check
```

Both files live in the same folder. `--check` runs the whole self-test,
including the refusals, and needs no client.

### Point a client at it

**Claude Code**

```sh
claude mcp add siw-charting -- python3 /full/path/to/siw_charting.py
```

**Claude Desktop** — `~/Library/Application Support/Claude/claude_desktop_config.json`
on macOS, `%APPDATA%\\Claude\\claude_desktop_config.json` on Windows.

**Cursor** — `~/.cursor/mcp.json`, or `.cursor/mcp.json` per project.

Config paths move between versions; the block inside is the same
everywhere:

```json
{
  "mcpServers": {
    "siw-charting": {
      "command": "python3",
      "args": ["/full/path/to/siw_charting.py"]
    }
  }
}
```

## Tools

| tool | what it gives you |
|---|---|
| `draft_note` | template for the note, wording to avoid, decisions behind it |
| `next_step` | what to do besides writing it down, in order |
| `search_charting` | find articles by situation |
| `read_article` | a whole article by slug |
| `find_phrases` | stronger wording for a situation |
| `words_to_avoid` | wording that reads badly later, and what to write instead |
| `charting_cases` | the decisions themselves — court, year, link |
| `list_sections` | everything, grouped, in reading order |

It also ships **prompts**: clients that support them show two ready
conversations — *Help me write this note* and *What do I do now* — and
both carry the rules with them: never ask for patient identifiers, never
invent a finding, name the decision so the nurse can check you.

## Where the content comes from

Every rule in the guide stands on a published decision on
[CourtListener](https://www.courtlistener.com/), linked so you can read
it yourself. Where only a docket entry was available and not the opinion,
the case is left out — a decision nobody can open is a citation, not
evidence.

Written by a medical-surgical registered nurse, ten years, day shift.
Not legal advice and not clinical advice.

- The guide: <https://shiftiswild.com/notes/>
- Every decision in one page: <https://shiftiswild.com/notes/cases/>
- Machine-readable manifest: <https://shiftiswild.com/notes/mcp.json>
- The corpus as JSON: <https://shiftiswild.com/notes/corpus.json>

## Licence

Code — MIT. Content in `corpus.json` — CC BY 4.0: use it, quote it, build
on it, with a link back.

The source comments are in Russian; the project is written that way. The
tool descriptions, prompts and everything a user sees are in English.
