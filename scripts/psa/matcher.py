"""Best-effort linking between mirror `cards` and PSA `psa_variants`.

PSA and the mirror name sets completely differently - and not just
formatting: PSA calls the 1999 flagship set "Game", the mirror calls it
"Base" (set id "base1"). Name-token overlap alone can't bridge that gap.

The naive fix - fall back to comparing the *set* of card numbers - turns out
to be unreliable on its own: Pokemon sets are numbered sequentially from 1,
so any two same-year sets of similar size look deceptively similar under
plain Jaccard overlap (e.g. {1..83} vs {1..85} is 98% "overlap" despite being
two different sets). So this requires a genuinely strong signal rather than
blending two weak ones: either a near-exact name-token match, or a
near-exact number match *and* matching set size. Sets not yet scraped (no
numbers available yet) can only use the name signal.

This is a heuristic, not a guarantee - a variant that isn't linked here still
has its full price history in `psa_prices`, it's just not joined to a mirror
card yet. Re-running replaces the whole match table, so it's safe to re-run
after fixing the heuristic or adding more mirror data.
"""
import re

from . import db

STOPWORDS = {"poke", "mon", "pokemon"}
STRONG_NAME = 0.5
STRONG_NUMBER_JACCARD = 0.85
STRONG_NUMBER_SIZE_RATIO = 0.85
ACCEPT_THRESHOLD = 0.5

# The mirror abbreviates some era prefixes in sub-set names (e.g. set_name
# "HS-Unleashed" for what PSA slugs as "...heartgold-soulsilver-unleashed").
# Expand the abbreviation so both sides tokenize to the same words.
ABBREVIATIONS = {
    "hs": ["heartgold", "soulsilver"],
    "dp": ["diamond", "pearl"],
    "bw": ["black", "white"],
    "sm": ["sun", "moon"],
    "swsh": ["sword", "shield"],
}

# A handful of PSA slugs that no automated signal handles well, confirmed by
# hand. "Base II" is PSA's name for the 2000 reprint set that pokemontcg.io
# calls "Base Set 2" (base4) - the roman numeral doesn't tokenize anywhere
# near "2", and its number/name overlap with the original Base Set (base1,
# which Base Set 2 deliberately reused numbers/art from) is genuinely
# ambiguous to a heuristic.
MANUAL_SET_OVERRIDES = {
    "2000-poke-mon-base-ii": "base4",
}


def _token_sequence(s):
    s = re.sub(r"^\d{4}\s*", "", (s or "").lower())  # drop a leading year, it's not part of the name
    s = s.replace("'", "")  # PSA slugs drop apostrophes ("Champion's Path" -> "champions-path");
    s = re.sub(r"[^a-z0-9]+", " ", s)  # matching the raw mirror name needs the same deletion, not a split
    tokens = []
    for t in s.split():
        if not t or t in STOPWORDS:
            continue
        tokens.extend(ABBREVIATIONS.get(t, [t]))
    return tokens


def _tokens(s):
    return set(_token_sequence(s))


def _jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _name_similarity(slug, name):
    """Bag-of-words Jaccard, with a boost when `name`'s words are exactly the
    trailing words of `slug`. PSA slugs the whole product name - era prefix
    then specific set name, e.g. "sword-shield-evolving-skies" - so the era
    prefix alone (e.g. "Sword & Shield", itself also a real set) would
    otherwise tie against every set released in that era. The specific set
    name PSA actually means is the suffix, so an exact ordered suffix match
    is much stronger evidence than an unordered bag-of-words score."""
    slug_seq, name_seq = _token_sequence(slug), _token_sequence(name)
    if name_seq and slug_seq[-len(name_seq) :] == name_seq:
        return 1.0
    return _jaccard(set(slug_seq), set(name_seq))


def _set_pair_score(name_score, psa_numbers, mirror_numbers):
    """Accept on one clearly strong signal, not a blend of two weak ones."""
    number_score = 0.0
    if psa_numbers and mirror_numbers:
        j = _jaccard(psa_numbers, mirror_numbers)
        size_ratio = min(len(psa_numbers), len(mirror_numbers)) / max(len(psa_numbers), len(mirror_numbers))
        if j >= STRONG_NUMBER_JACCARD and size_ratio >= STRONG_NUMBER_SIZE_RATIO:
            number_score = j

    if name_score >= STRONG_NAME or number_score >= STRONG_NUMBER_JACCARD:
        return max(name_score, number_score)
    if name_score > 0 and number_score > 0:
        return 0.5 * name_score + 0.5 * number_score  # weak-weak agreement, still capped low
    return max(name_score, number_score)


def build_set_mapping(conn):
    """Returns {psa_set_id: (mirror_set_id, score)} for the best guess per PSA set."""
    psa_sets = [dict(r) for r in conn.execute("SELECT * FROM psa_sets WHERE is_japanese = 0").fetchall()]
    mirror_sets = [
        dict(r)
        for r in conn.execute("SELECT DISTINCT set_id, set_name, series, release_date FROM cards").fetchall()
    ]
    for ms in mirror_sets:
        year_str = (ms.get("release_date") or "")[:4]
        ms["year"] = int(year_str) if year_str.isdigit() else None
        ms["numbers"] = {
            r["number"]
            for r in conn.execute("SELECT DISTINCT number FROM cards WHERE set_id = ?", (ms["set_id"],)).fetchall()
            if r["number"]
        }

    psa_numbers_by_set = {}
    for r in conn.execute("SELECT DISTINCT psa_set_id, card_number FROM psa_variants WHERE card_number IS NOT NULL"):
        psa_numbers_by_set.setdefault(r["psa_set_id"], set()).add(r["card_number"])

    mapping = {}
    for ps in psa_sets:
        if ps["slug"] in MANUAL_SET_OVERRIDES:
            mapping[ps["psa_set_id"]] = (MANUAL_SET_OVERRIDES[ps["slug"]], 1.0)
            continue

        psa_numbers = psa_numbers_by_set.get(ps["psa_set_id"], set())
        # Deliberately compares against set_name only, not `series` - a mirror
        # "series" (e.g. "Sword & Shield") is shared by a dozen+ sets, so
        # matching against it produces ties across an entire era rather than
        # identifying one set.
        scored = []
        for ms in mirror_sets:
            if ms["year"] is None or ps["year"] is None or abs(ms["year"] - ps["year"]) > 1:
                continue
            name_score = _name_similarity(ps["slug"], ms.get("set_name") or "")
            score = _set_pair_score(name_score, psa_numbers, ms["numbers"])
            if score >= ACCEPT_THRESHOLD:
                scored.append((score, ms))

        if not scored:
            continue
        scored.sort(key=lambda pair: pair[0], reverse=True)
        best_score, best = scored[0]
        if len(scored) > 1 and scored[1][0] == best_score:
            continue  # ambiguous tie between two candidates - skip rather than guess
        mapping[ps["psa_set_id"]] = (best["set_id"], best_score)
    return mapping, len(psa_sets)


def match_all():
    with db.connection() as conn:
        set_mapping, total_psa_sets = build_set_mapping(conn)
        print(f"Matched {len(set_mapping)} of {total_psa_sets} PSA sets to a mirror set (by year + name overlap).")

        conn.execute("DELETE FROM card_psa_match")

        variants = [dict(r) for r in conn.execute("SELECT * FROM psa_variants").fetchall()]
        matched = 0

        for v in variants:
            mapped = set_mapping.get(v["psa_set_id"])
            if not mapped:
                continue
            mirror_set_id, set_score = mapped

            raw_number = v["card_number"]
            stripped_number = (raw_number or "").lstrip("0") or raw_number
            candidates = conn.execute(
                "SELECT * FROM cards WHERE set_id = ? AND number IN (?, ?)",
                (mirror_set_id, raw_number, stripped_number),
            ).fetchall()
            if not candidates:
                continue

            base_name = v["base_name"] or v["description"]
            best_card, best_name_score = None, -1.0
            for c in candidates:
                score = _name_similarity(base_name, c["name"] or "")
                if score > best_name_score:
                    best_card, best_name_score = c, score
            if best_card is None:
                continue

            confidence = round(0.5 * set_score + 0.5 * max(best_name_score, 0.3), 3)
            conn.execute(
                """
                INSERT INTO card_psa_match (card_id, psa_spec_id, match_method, match_confidence)
                VALUES (?, ?, 'auto_number_name', ?)
                ON CONFLICT(card_id, psa_spec_id) DO UPDATE SET
                    match_method=excluded.match_method,
                    match_confidence=excluded.match_confidence
                """,
                (best_card["id"], v["psa_spec_id"], confidence),
            )
            matched += 1

    print(f"Card matching complete: {matched} of {len(variants)} PSA variants linked to a mirror card.")
    return matched


if __name__ == "__main__":
    match_all()
