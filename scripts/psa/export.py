"""Builds data/psa/{meta,by-card-id,unmatched}.json from the scratch db."""
import json
from datetime import datetime, timezone
from pathlib import Path

from . import db


def export(out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)

    with db.connection() as conn:
        variants = {
            r["psa_spec_id"]: dict(r)
            for r in conn.execute(
                """
                SELECT v.*, s.slug AS psa_set_slug, s.display_name AS psa_set_name
                FROM psa_variants v JOIN psa_sets s ON s.psa_set_id = v.psa_set_id
                """
            ).fetchall()
        }

        latest_prices_by_spec = {}
        for r in conn.execute("SELECT * FROM psa_prices_latest"):
            latest_prices_by_spec.setdefault(r["psa_spec_id"], {})[str(r["grade"])] = r["price"]

        matches = conn.execute("SELECT * FROM card_psa_match").fetchall()
        matched_spec_ids = set()

        by_card_id = {}
        for m in matches:
            v = variants.get(m["psa_spec_id"])
            if v is None:
                continue
            matched_spec_ids.add(m["psa_spec_id"])
            by_card_id.setdefault(m["card_id"], []).append(
                {
                    "psaSpecId": v["psa_spec_id"],
                    "psaSetId": v["psa_set_id"],
                    "description": v["description"],
                    "cardNumber": v["card_number"],
                    "variantTag": v["variant_tag"],
                    "matchConfidence": m["match_confidence"],
                    "grades": latest_prices_by_spec.get(v["psa_spec_id"], {}),
                }
            )

        unmatched = []
        for spec_id, v in variants.items():
            if spec_id in matched_spec_ids:
                continue
            unmatched.append(
                {
                    "psaSpecId": v["psa_spec_id"],
                    "psaSetId": v["psa_set_id"],
                    "psaSetSlug": v["psa_set_slug"],
                    "psaSetName": v["psa_set_name"],
                    "description": v["description"],
                    "cardNumber": v["card_number"],
                    "grades": latest_prices_by_spec.get(v["psa_spec_id"], {}),
                }
            )

        total_price_points = conn.execute("SELECT COUNT(*) FROM psa_prices").fetchone()[0]
        total_sets = conn.execute("SELECT COUNT(*) FROM psa_sets").fetchone()[0]

    meta = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "source": "https://www.psacard.com/priceguide",
        "sourceNote": (
            "Scraped from PSA's public Price Guide. PSA only publishes grades "
            "NM 7 / NM-MT 8 / MT 9 / GEM-MT 10 there (not every set shows all "
            "four), and only those grades appear here - grades 1-6, Authentic, "
            "and full auction history require a PSA/Collectors.com account "
            "login this project does not automate. This is a separate, "
            "independently-sourced dataset from data/psa-cache.json (which is "
            "fed by NEW POKEMON SCANNER's live PokemonPriceTracker.com "
            "lookups) - different source, different provenance, not merged. "
            "Regenerated on a schedule by .github/workflows/refresh-psa-data.yml; "
            "each commit that changes this data is effectively a dated "
            "snapshot, since this file always reflects only the latest scrape."
        ),
        "totalPsaSets": total_sets,
        "totalVariants": len(variants),
        "totalPricePoints": total_price_points,
        "matchedToCards": len(matched_spec_ids),
        "unmatchedVariants": len(unmatched),
        "matchMethod": (
            "Heuristic, not exact. Sets matched by release year + set-name "
            "token overlap (falling back to comparing card-number checklists "
            "when names disagree). Cards within a matched set matched by "
            "card number + name overlap. See matchConfidence per entry; a "
            "handful of vintage sets needed a manual override "
            "(see psa/matcher.py's MANUAL_SET_OVERRIDES)."
        ),
    }

    (out_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "by-card-id.json").write_text(
        json.dumps(by_card_id, ensure_ascii=False, sort_keys=True, indent=None), encoding="utf-8"
    )
    (out_dir / "unmatched.json").write_text(
        json.dumps(unmatched, ensure_ascii=False, indent=None), encoding="utf-8"
    )

    print(f"Exported to {out_dir}:")
    print(f"  meta.json")
    print(f"  by-card-id.json  - {len(by_card_id)} mirror cards, {len(matched_spec_ids)} PSA variants")
    print(f"  unmatched.json   - {len(unmatched)} PSA variants not linked to a mirror card")
