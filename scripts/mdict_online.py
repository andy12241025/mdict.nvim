#!/usr/bin/env python3
"""Look up a word using the Free Dictionary API (dictionaryapi.dev)."""

import json
import sys
import urllib.request
import urllib.error


def lookup(word: str) -> str | None:
    url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{urllib.request.quote(word)}"
    req = urllib.request.Request(url, headers={"User-Agent": "mdict-nvim/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
        return None

    if not isinstance(data, list) or not data:
        return None

    lines: list[str] = []
    entry = data[0]

    # Header: word + phonetic
    header = entry.get("word", word)
    phonetic = entry.get("phonetic", "")
    if phonetic:
        header += f"  {phonetic}"
    lines.append(header)
    lines.append("")

    sense_num = 0
    for meaning in entry.get("meanings", []):
        pos = meaning.get("partOfSpeech", "")
        if pos:
            lines.append(f"  ━━ {pos} ━━")

        for defn in meaning.get("definitions", []):
            sense_num += 1
            d = defn.get("definition", "")
            if d:
                lines.append(f"  {sense_num}. {d}")
            example = defn.get("example", "")
            if example:
                lines.append(f"     ◆ {example}")

        syns = meaning.get("synonyms", [])
        if syns:
            lines.append(f"     SYN: {', '.join(syns[:8])}")
        ants = meaning.get("antonyms", [])
        if ants:
            lines.append(f"     ANT: {', '.join(ants[:8])}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n" if lines else None


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: mdict_online.py WORD", file=sys.stderr)
        sys.exit(1)

    word = sys.argv[1]
    result = lookup(word)
    if result is None:
        sys.exit(1)
    print(result)


if __name__ == "__main__":
    main()
