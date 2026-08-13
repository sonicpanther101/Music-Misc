"""
Last.fm client - pulls your top artists and top albums, with scrobble counts.

Uses the official, documented, no-auth-needed-for-reads Last.fm API:
  https://www.last.fm/api/show/user.getTopArtists
  https://www.last.fm/api/show/user.getTopAlbums
"""

import time
import requests

API_ROOT = "https://ws.audioscrobbler.com/2.0/"


class LastFmError(Exception):
    pass


class LastFmClient:
    def __init__(self, api_key, username, request_delay=1.0):
        self.api_key = api_key
        self.username = username
        self.request_delay = request_delay
        self.session = requests.Session()

    def _call(self, method, **params):
        query = {
            "method": method,
            "user": self.username,
            "api_key": self.api_key,
            "format": "json",
        }
        query.update(params)
        resp = self.session.get(API_ROOT, params=query, timeout=20)
        time.sleep(self.request_delay)
        data = resp.json()
        if "error" in data:
            raise LastFmError(
                f"Last.fm API error {data['error']}: {data.get('message')}"
            )
        return data

    def get_top_artists(self, period="overall", limit=100):
        """
        Returns a list of dicts: {name, playcount, rank, mbid, url}
        sorted by playcount descending (Last.fm already sorts this way).
        """
        artists = []
        per_page = 200  # last.fm allows up to 1000, but keep pages manageable
        page = 1
        while len(artists) < limit:
            remaining = limit - len(artists)
            data = self._call(
                "user.gettopartists",
                period=period,
                limit=min(per_page, remaining),
                page=page,
            )
            top = data.get("topartists", {})
            artist_list = top.get("artist", [])
            if not artist_list:
                break
            for a in artist_list:
                artists.append({
                    "name": a.get("name"),
                    "playcount": int(a.get("playcount", 0)),
                    "rank": a.get("@attr", {}).get("rank"),
                    "mbid": a.get("mbid") or None,
                    "url": a.get("url"),
                })
            total_pages = int(top.get("@attr", {}).get("totalPages", 1))
            if page >= total_pages:
                break
            page += 1
        return artists[:limit]

    def get_top_albums_for_artist(self, artist_name, limit=3):
        """
        Last.fm doesn't have a direct "top albums by this artist for this
        user" endpoint that's reliable, so we use user.gettopalbums filtered
        by artist name client-side isn't available either - instead we use
        artist-scoped library data via user.gettopalbums (global top albums)
        and filter. For per-artist album scrobble counts, the most reliable
        public endpoint is actually:
            user.getTopAlbums does NOT take an artist filter.
        So instead we fetch the user's overall top albums once (cached by
        caller) and filter client-side. See get_top_albums_overall().
        """
        raise NotImplementedError("Use get_top_albums_overall() and filter client-side")

    def get_top_albums_overall(self, period="overall", limit=1000):
        """
        Returns a list of dicts: {artist, album, playcount, mbid, url}
        This pulls your overall top albums list (across all artists), which
        we then filter client-side per-artist in main.py. Last.fm's API has
        no "top albums BY a specific artist FOR this user" endpoint, so this
        is the correct way to get real per-album scrobble counts.
        """
        albums = []
        per_page = 200
        page = 1
        while len(albums) < limit:
            remaining = limit - len(albums)
            data = self._call(
                "user.gettopalbums",
                period=period,
                limit=min(per_page, remaining),
                page=page,
            )
            top = data.get("topalbums", {})
            album_list = top.get("album", [])
            if not album_list:
                break
            for al in album_list:
                albums.append({
                    "artist": al.get("artist", {}).get("name"),
                    "album": al.get("name"),
                    "playcount": int(al.get("playcount", 0)),
                    "mbid": al.get("mbid") or None,
                    "url": al.get("url"),
                })
            total_pages = int(top.get("@attr", {}).get("totalPages", 1))
            if page >= total_pages:
                break
            page += 1
        return albums[:limit]
