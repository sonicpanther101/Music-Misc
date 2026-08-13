"""
The "is this worth buying" scoring formula.

Philosophy: you listen to a LOT of music (700+ artists/year), so plain
"price" doesn't tell you much - what matters is price relative to how much
you actually listen to that artist/album. This gives a transparent,
editable score so you can re-sort in Excel/Sheets however you like; it is
NOT meant to be the final word, just a reasonable starting ranking.

score = (artist_scrobbles_weight * normalized_artist_scrobbles
         + album_scrobbles_weight * normalized_album_scrobbles)
        / price_weight_factor

Where "normalized" means scaled 0-1 relative to the max in your whole
dataset, so one mega-favourite artist doesn't break the scale for everyone
else. Price factor uses a soft curve (sqrt) rather than a straight linear
divide, so a $5 difference matters a lot at the cheap end but not much at
the expensive end - this matches how people actually feel about price.

All of this is just arithmetic on columns that are ALSO in the CSV, so you
can throw this formula out entirely and build your own in a spreadsheet.
"""

import math


def compute_scores(rows):
    """
    rows: list of dicts, each must have:
        artist_scrobbles (int)
        album_scrobbles (int or None)
        best_price_nzd (float or None)  -- the cheapest valid price found
    Adds a "value_score" key to each row (float, higher = better deal) and
    a "cost_per_artist_scrobble" / "cost_per_album_scrobble" key.
    Rows with no valid price get value_score = None (can't rank what you
    can't buy).
    """
    max_artist_scrobbles = max((r["artist_scrobbles"] for r in rows), default=1) or 1
    max_album_scrobbles = max(
        (r["album_scrobbles"] for r in rows if r.get("album_scrobbles")),
        default=1,
    ) or 1

    for r in rows:
        price = r.get("best_price_nzd")
        artist_s = r.get("artist_scrobbles") or 0
        album_s = r.get("album_scrobbles") or 0

        r["cost_per_artist_scrobble"] = (
            round(price / artist_s, 4) if price and artist_s else None
        )
        r["cost_per_album_scrobble"] = (
            round(price / album_s, 4) if price and album_s else None
        )

        if not price or price <= 0:
            r["value_score"] = None
            continue

        norm_artist = artist_s / max_artist_scrobbles
        norm_album = (album_s / max_album_scrobbles) if album_s else 0

        # weight album scrobbles higher when we have them (more specific
        # signal than artist-level interest), but don't let a missing
        # album scrobble count zero out the score entirely
        interest = (0.4 * norm_artist) + (0.6 * norm_album) if album_s else norm_artist

        # soft price penalty: sqrt curve means doubling the price doesn't
        # halve the score, it reduces it by ~30% - reflects that $40 vs $20
        # matters more to most people than $140 vs $120
        price_penalty = math.sqrt(price)

        r["value_score"] = round((interest * 100) / price_penalty, 3)

    return rows
