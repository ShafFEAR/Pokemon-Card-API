"""Builds data/psa-cardfacts/{meta,by-card-id,unmatched}.json from the scratch db
plus the per-grade prices psa.cardfacts_scraper returned."""
import json
from datetime import datetime, timezone
from pathlib import Path

from . import db

# A "most recent" sale this far from the grade's average is more likely a
# mislabeled or broken listing than a real market move (e.g. a 1st Edition
# Alakazam PSA 9 "most recent" of $77 against a $1,502 average). Still
# published as PSA shows it - just flagged so consumers can fall back to
# `average`.
SUSPECT_RATIO = 4.0


def _flag_suspect(grades):
    for g in grades.values():
        recent, avg = g.get("mostRecent"), g.get("average")
        if recent and avg and (recent > avg * SUSPECT_RATIO or recent * SUSPECT_RATIO < avg):
            g["suspect"] = True
    return grades


def export(out_dir: Path, prices, cards, total_checklist_entries):
    out_dir.mkdir(parents=True, exist_ok=True)
    url_by_id = {c["cardfactsId"]: c["url"] for c in cards}

    with db.connection() as conn:
        variants = {
            r["psa_spec_id"]: dict(r)
            for r in conn.execute(
                """
                SELECT v.*, s.display_name AS psa_set_name
                FROM psa_variants v JOIN psa_sets s ON s.psa_set_id = v.psa_set_id
                """
            ).fetchall()
        }
        matches = conn.execute("SELECT * FROM card_psa_match").fetchall()
        total_sets = conn.execute("SELECT COUNT(*) FROM psa_sets").fetchone()[0]

    def entry(v):
        return {
            "cardfactsId": v["psa_spec_id"],
            "url": url_by_id.get(v["psa_spec_id"]),
            "psaSetName": v["psa_set_name"],  # the only place 1st Edition shows for e.g. Neo Genesis
            "description": v["description"],
            "cardNumber": v["card_number"],
            "variantTag": v["variant_tag"],
            "grades": _flag_suspect(prices.get(v["psa_spec_id"], {})),
        }

    by_card_id = {}
    matched_ids = set()
    for m in matches:
        v = variants.get(m["psa_spec_id"])
        if v is None or v["psa_spec_id"] not in prices:
            continue
        matched_ids.add(v["psa_spec_id"])
        by_card_id.setdefault(m["card_id"], []).append({**entry(v), "matchConfidence": m["match_confidence"]})

    unmatched = [
        entry(v)
        for spec_id, v in variants.items()
        if spec_id not in matched_ids and spec_id in prices
    ]

    priced = sum(1 for g in prices.values() if any(e.get("mostRecent") for e in g.values()))
    meta = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "source": "https://www.psacard.com/cardfacts",
        "sourceNote": (
            "Scraped from PSA CardFacts card pages, which are public (no login) and show, per "
            "grade 1-10 + Authentic: the most recent sale price, average sale price, PSA's price "
            "and population. mostRecentDate is that sale's date, taken from the page's own sales "
            "list. CardFacts covers only a curated subset of mostly vintage cards - most Pokemon "
            "cards have no CardFacts page, and PSA's full Auction Prices Realized needs a "
            "Collectors.com login this project does not automate. A grade flagged suspect has a "
            "most recent sale more than 4x away from its average (likely a mislabeled listing). "
            "Separate from data/psa/ (Price Guide values, grades 7-10) - not merged. Regenerated "
            "monthly by .github/workflows/refresh-cardfacts-data.yml; each commit that changes "
            "this data is effectively a dated snapshot."
        ),
        "totalCardfactsSets": total_sets,
        "totalChecklistEntries": total_checklist_entries,
        "cardPages": len(cards),
        "cardPagesScraped": len(prices),
        "cardPagesWithRecentSale": priced,
        "matchedToCards": len(matched_ids),
        "matchedMirrorCardIds": len(by_card_id),
        "unmatched": len(unmatched),
        "matchMethod": (
            "Same heuristic as data/psa/ (psa/matcher.py): sets by release year + set-name "
            "tokens (or card-number checklist), cards by number + name. Japanese sets are never "
            "matched (the mirror has no Japanese cards) and land in unmatched.json."
        ),
    }

    (out_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "by-card-id.json").write_text(
        json.dumps(by_card_id, ensure_ascii=False, sort_keys=True), encoding="utf-8"
    )
    (out_dir / "unmatched.json").write_text(json.dumps(unmatched, ensure_ascii=False), encoding="utf-8")

    print(f"Exported to {out_dir}:")
    print(f"  by-card-id.json  - {len(by_card_id)} mirror cards, {len(matched_ids)} CardFacts pages")
    print(f"  unmatched.json   - {len(unmatched)} CardFacts pages not linked to a mirror card")
