#!/usr/bin/env python3
"""Look up a word in an MDict (.mdx) dictionary and print a formatted definition."""

import argparse
import html
import re
import sys

from mdict_mquery import IndexBuilder

MAX_REDIRECTS = 5


def _text(fragment: str) -> str:
    """Strip all XML/HTML tags and unescape entities from a fragment."""
    t = re.sub(r"<[^>]+>", "", fragment)
    return html.unescape(t).strip()


def _extract_pron(raw: str) -> str:
    """Extract pronunciation like 'BrE /həˈləʊ/  NAmE /həˈloʊ/' from the first top-g block."""
    topg = re.search(r"<top-g>(.*?)</top-g>", raw, re.DOTALL)
    if not topg:
        return ""
    prons = []
    for m in re.finditer(r"<pron-g-blk>(.*?)</pron-g-blk>", topg.group(1), re.DOTALL):
        inner = m.group(1)
        label = "BrE" if "brelabel" in inner else ("NAmE" if "namelabel" in inner else "")
        phon = re.search(r"<phon>([^<]+)</phon>", inner)
        if phon:
            prons.append(f"{label} /{phon.group(1)}/")
    return "  ".join(prons)


def _collect_pos(raw: str) -> str:
    """Collect all part-of-speech labels (from both <pos> and <xpos> tags)."""
    parts: list[str] = []
    for m in re.finditer(r"<x?pos>(?:<[^>]+>)*([^<]+)(?:<[^>]+>)*</x?pos>", raw):
        p = m.group(1).strip()
        if p and p not in parts:
            parts.append(p)
    return ", ".join(parts)


def _extract_headword(raw: str) -> str:
    m = re.search(r"<h [^>]*>([^<]+)</h>", raw)
    return m.group(1).strip() if m else ""


def format_entry(raw: str) -> str:
    # ── Remove noise ──
    raw = re.sub(r"<head>.*?</head>", "", raw, flags=re.DOTALL | re.IGNORECASE)
    raw = re.sub(r"<script[^>]*>.*?</script>", "", raw, flags=re.DOTALL | re.IGNORECASE)
    raw = re.sub(r"<audio[\s>].*?</audio>", "", raw, flags=re.DOTALL | re.IGNORECASE)
    raw = re.sub(r"<audio-[^>]*>.*?</audio-[^>]*>", "", raw, flags=re.DOTALL)
    raw = re.sub(r"<a[^>]*>🔊</a>", "", raw)
    raw = raw.replace("🔊", "")
    raw = re.sub(r"<fthzmark>.*?</fthzmark>", "", raw, flags=re.DOTALL)
    raw = re.sub(r"<hkey>.*?</hkey>", "", raw, flags=re.DOTALL)
    raw = re.sub(r'<symbol type="key">🔑</symbol>', "", raw)
    raw = raw.replace("🔑", "")
    # POS navigation div (e.g. "verb, noun" jump links)
    raw = re.sub(r'<div class="cixing_tiaozhuan">.*?</div>\s*</div>', "", raw, flags=re.DOTALL)

    # ── Header extraction ──
    headword = _extract_headword(raw)
    pron_line = _extract_pron(raw)
    pos_str = _collect_pos(raw)

    lines: list[str] = []
    title = headword
    if pos_str:
        title += f"  ({pos_str})"
    if title:
        lines.append(title)
    if pron_line:
        lines.append(pron_line)
    lines.append("")

    # ── Remove header blocks we already extracted ──
    body = raw
    # Remove subentry top-g (contains POS + verb form pronunciations) FIRST
    body = re.sub(r"<subentry-g[^>]*>\s*<top-g>.*?</top-g>", "", body, flags=re.DOTALL)
    # Remove the main (first) top-g only
    body = re.sub(r"<top-g>.*?</top-g>", "", body, count=1, flags=re.DOTALL)
    # Remove verb-form / inflection blocks
    body = re.sub(r"<vp-gs[^>]*>.*?</vp-gs>", "", body, flags=re.DOTALL)
    body = re.sub(r"<v-gs[^>]*>.*?</v-gs>", "", body, flags=re.DOTALL)
    body = re.sub(r"<if-gs[^>]*>.*?</if-gs>", "", body, flags=re.DOTALL)
    body = re.sub(r"<res-g[^>]*>.*?</res-g>", "", body, flags=re.DOTALL)

    # ── Section headers: ➤ topic Chinese ──
    def _format_section(m: re.Match) -> str:
        shcut = _text(m.group(1))
        return f"\nSEC:{shcut}\n"

    body = re.sub(
        r"<sdsymb>.*?</sdsymb>\s*<shcut>(.*?)</shcut>",
        _format_section,
        body,
        flags=re.DOTALL,
    )

    # Remove sn-blk open tags (structural, not content)
    body = re.sub(r"<sn-blk[^>]*>", "", body)

    # ── Definitions ──
    body = re.sub(r"<def[^>]*>", "\nDEF:", body)
    body = re.sub(r"</def>", "\n", body)

    # ── Examples ──
    body = re.sub(r"<xsymb>.*?</xsymb>", "\nEXM:", body, flags=re.DOTALL)

    # ── Chinese separator ──
    body = re.sub(r"<chnsep>\s*</chnsep>", " ", body)

    # ── Unbox/synonym panel titles ──
    body = re.sub(r"<titled>([^<]*)</titled>", r"\nBOX:\1\n", body)

    # ── Phrasal verbs ──
    body = body.replace("●", "\nPHR:")

    # ── Cross-references ──
    body = re.sub(r"<xr-gs[^>]*>.*?<xh>([^<]*)</xh>.*?</xr-gs>", r" \1 ", body, flags=re.DOTALL)

    # ── Grammar/register labels ──
    body = re.sub(r"<gl-blk>.*?<gl>([^<]*)</gl>.*?</gl-blk>", r" [\1] ", body, flags=re.DOTALL)
    body = re.sub(r"<cl-blk>.*?<cl>([^<]*)</cl>.*?</cl-blk>", r" [\1] ", body, flags=re.DOTALL)
    body = re.sub(r"<reg-blk>.*?<reg>([^<]*)</reg>.*?</reg-blk>", r" (\1) ", body, flags=re.DOTALL)
    body = re.sub(r"<geo-blk>.*?<geo>([^<]*)</geo>.*?</geo-blk>", r" (\1) ", body, flags=re.DOTALL)

    # ── Inline line breaks ──
    body = re.sub(r"<xhtml:br\s*/?>", "\n", body, flags=re.IGNORECASE)
    body = re.sub(r"<br\s*/?>", "\n", body, flags=re.IGNORECASE)
    body = re.sub(r"</li>|</licontent>", "\n", body, flags=re.IGNORECASE)

    # ── Strip all remaining tags ──
    body = re.sub(r"<[^>]+>", "", body)
    body = html.unescape(body)

    # ── Post-process into formatted lines ──
    sense_num = 0
    for raw_line in body.split("\n"):
        raw_line = raw_line.strip()
        if not raw_line:
            continue

        if raw_line.startswith("SEC:"):
            label = raw_line[4:].strip()
            if label:
                lines.append(f"\n  ━━ {label} ━━")
            continue

        if raw_line.startswith("DEF:"):
            sense_num += 1
            defn = re.sub(r"\s{2,}", " ", raw_line[4:]).strip()
            if defn:
                lines.append(f"  {sense_num}. {defn}")
            continue

        if raw_line.startswith("EXM:"):
            ex = re.sub(r"\s{2,}", " ", raw_line[4:]).strip()
            if ex:
                lines.append(f"     ◆ {ex}")
            continue

        if raw_line.startswith("BOX:"):
            box_title = raw_line[4:].strip()
            lines.append(f"\n  ┌─ {box_title} ─┐")
            continue

        if raw_line.startswith("PHR:"):
            phr = re.sub(r"\s{2,}", " ", raw_line[4:]).strip()
            if phr:
                lines.append(f"\n  ● {phr}")
            continue

        text = re.sub(r"\s{2,}", " ", raw_line).strip()
        if not text:
            continue
        if text.startswith("◆"):
            lines.append(f"     {text}")
        elif text.startswith("➡"):
            lines.append(f"  {text}")
        elif text.startswith("*"):
            lines.append(f"       {text}")
        elif text.startswith("SYN"):
            lines.append(f"     {text}")
        else:
            lines.append(f"     {text}")

    output = "\n".join(lines)
    output = re.sub(r"\n{3,}", "\n\n", output)
    return output.rstrip() + "\n"


def _stem_candidates(word: str) -> list[str]:
    """Generate possible base forms by stripping English inflectional suffixes."""
    w = word.lower()
    candidates: list[str] = []
    # -ies -> -y  (batteries -> battery)
    if w.endswith("ies") and len(w) > 4:
        candidates.append(w[:-3] + "y")
    # -ves -> -f / -fe  (wolves -> wolf, knives -> knife)
    if w.endswith("ves") and len(w) > 4:
        candidates.append(w[:-3] + "f")
        candidates.append(w[:-3] + "fe")
    # -ses / -xes / -zes / -ches / -shes -> drop -es
    if w.endswith("es") and len(w) > 3:
        if w.endswith(("ses", "xes", "zes", "ches", "shes")):
            candidates.append(w[:-2])
    # -s (general plural / 3rd person)
    if w.endswith("s") and not w.endswith("ss") and len(w) > 3:
        candidates.append(w[:-1])
    # -ed -> base, -ed -> -e  (stopped -> stop, loved -> love)
    if w.endswith("ed") and len(w) > 4:
        candidates.append(w[:-2])
        candidates.append(w[:-1])  # drop d only -> base + e
        # doubled consonant: stopped -> stop
        if len(w) > 5 and w[-3] == w[-4]:
            candidates.append(w[:-3])
    # -ing -> base, -ing -> -e  (running -> run, making -> make)
    if w.endswith("ing") and len(w) > 5:
        candidates.append(w[:-3])
        candidates.append(w[:-3] + "e")
        # doubled consonant: running -> run
        if len(w) > 6 and w[-4] == w[-5]:
            candidates.append(w[:-4])
    # -er -> base, -er -> -e  (bigger -> big, wider -> wide)
    if w.endswith("er") and len(w) > 4:
        candidates.append(w[:-2])
        candidates.append(w[:-1])  # drop r -> base + e
        if len(w) > 5 and w[-3] == w[-4]:
            candidates.append(w[:-3])
    # -est -> base, -est -> -e  (biggest -> big, widest -> wide)
    if w.endswith("est") and len(w) > 5:
        candidates.append(w[:-3])
        candidates.append(w[:-3] + "e")
        if len(w) > 6 and w[-4] == w[-5]:
            candidates.append(w[:-4])
    # -ly -> base, -ily -> -y  (happily -> happy, quickly -> quick)
    if w.endswith("ily") and len(w) > 4:
        candidates.append(w[:-3] + "y")
    if w.endswith("ly") and len(w) > 4:
        candidates.append(w[:-2])
    return candidates


def _resolve(ib: IndexBuilder, word: str) -> str | None:
    """Look up *word*, following @@@LINK= redirects up to MAX_REDIRECTS."""
    seen: set[str] = set()
    current = word
    for _ in range(MAX_REDIRECTS):
        if current.lower() in seen:
            return None
        seen.add(current.lower())
        results = ib.mdx_lookup(current, ignorecase=True)
        if not results:
            return None
        entry = results[0].strip()
        m = re.match(r"^@@@LINK=(.*)", entry, re.IGNORECASE)
        if m:
            current = m.group(1).strip()
            continue
        return entry
    return None


def lookup(ib: IndexBuilder, word: str) -> str | None:
    """Look up *word*, falling back to stemmed variants if not found."""
    entry = _resolve(ib, word)
    if entry is not None:
        return entry
    for candidate in _stem_candidates(word):
        entry = _resolve(ib, candidate)
        if entry is not None:
            return entry
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mdx", required=True, help="Path to .mdx file")
    parser.add_argument("--word", required=True, help="Word to look up")
    args = parser.parse_args()

    try:
        ib = IndexBuilder(args.mdx)
    except Exception as exc:
        print(f"Error loading dictionary: {exc}", file=sys.stderr)
        sys.exit(1)

    entry = lookup(ib, args.word)
    if entry is None:
        sys.exit(1)

    print(format_entry(entry))


if __name__ == "__main__":
    main()
