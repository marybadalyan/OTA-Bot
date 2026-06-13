"""
Spotify Playlist Exporter
-------------------------
Fetches all your playlists and exports: Playlist Name | Artist | Song Title
"""

import csv
import os
import sys
import time
import threading
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

import spotipy
from spotipy.oauth2 import SpotifyOAuth

# ── Config ────────────────────────────────────────────────────────────────────
CLIENT_ID     = "750d57379bb446a7b77facffbd74e146"
CLIENT_SECRET = "6e2e54ea11da4992900c553663609ce4"
PORT          = 5000
REDIRECT_URI  = f"http://127.0.0.1:{PORT}/callback"
OUTPUT_FILE   = "spotify_playlists.csv"
# ─────────────────────────────────────────────────────────────────────────────

_auth_code = {"value": None}
_server    = None


class CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if "code" in params:
            _auth_code["value"] = params["code"][0]
            body = b"<h2>&#x2705; Authenticated! You can close this tab.</h2>"
            self.send_response(200)
        else:
            body = b"<h2>&#x274C; No code received. Try again.</h2>"
            self.send_response(400)

        self.send_header("Content-Type", "text/html")
        self.send_header("ngrok-skip-browser-warning", "true")
        self.end_headers()
        self.wfile.write(body)

        threading.Thread(target=_server.shutdown).start()

    def log_message(self, *args):
        pass


def get_all_items(sp, result):
    items = list(result["items"])
    while result["next"]:
        result = sp.next(result)
        items.extend(result["items"])
    return items


def fetch_playlists(sp):
    me = sp.current_user()["id"]
    result = sp.current_user_playlists(limit=50)
    # Only playlists you own — followed playlists (owned by others) can't be
    # read via the API in Development mode and aren't really "yours" anyway.
    return [
        (p["name"], p["id"])
        for p in get_all_items(sp, result)
        if p and (p.get("owner") or {}).get("id") == me
    ]


def fetch_tracks(sp, playlist_id):
    result = sp.playlist_tracks(playlist_id, limit=100)
    tracks = []
    for item in get_all_items(sp, result):
        # Spotify returns the track payload under "item" (older clients used
        # "track"); accept either. Skip locals / empty rows.
        track = item.get("track") or item.get("item")
        if not track or item.get("is_local") or track.get("is_local"):
            continue
        artists = ", ".join(a["name"] for a in track.get("artists", []))
        tracks.append((artists, track.get("name", "Unknown")))
    return tracks


def export(sp, output_path, filter_name=None):
    print("Fetching your playlists…")
    all_playlists = fetch_playlists(sp)
    print(f"Found {len(all_playlists)} playlist(s).\n")

    if filter_name and filter_name != ".":
        playlists = [(n, i) for n, i in all_playlists if n == filter_name]
        if not playlists:
            print(f"❌  Playlist '{filter_name}' not found. Available playlists:")
            for name, _ in all_playlists:
                print(f"     • {name}")
            return
    else:
        playlists = all_playlists

    # When filtering to one playlist, merge into existing CSV rather than overwrite
    if filter_name and filter_name != ".":
        existing_rows = []
        if os.path.exists(output_path):
            with open(output_path, newline="", encoding="utf-8") as f:
                existing_rows = [r for r in csv.DictReader(f) if r["Playlist"] != filter_name]
    else:
        existing_rows = []

    rows = list(existing_rows)
    skipped = []
    for playlist_name, playlist_id in playlists:
        print(f"  ▸ {playlist_name}")
        try:
            for artist, song in fetch_tracks(sp, playlist_id):
                rows.append({"Playlist": playlist_name, "Artist": artist, "Song": song})
        except spotipy.SpotifyException as e:
            # Spotify-owned / algorithmic / editorial playlists return 403/404
            # for apps in Development mode — skip them and keep going.
            print(f"     ⚠️  Skipped (HTTP {e.http_status}) — not readable via the API.")
            skipped.append(playlist_name)

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["Playlist", "Artist", "Song"])
        writer.writeheader()
        writer.writerows(rows)

    exported = len(rows) - len(existing_rows)
    print(f"\n✅  Exported {exported} tracks → {output_path}")
    if skipped:
        print(f"⚠️  Skipped {len(skipped)} playlist(s) Spotify won't share via the API:")
        for name in skipped:
            print(f"     • {name}")


def main():
    global _server

    cache = ".spotify_token_cache"
    auth_manager = SpotifyOAuth(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        redirect_uri=REDIRECT_URI,
        scope="playlist-read-private playlist-read-collaborative",
        cache_path=cache,
        open_browser=False,
    )

    # Reuse a previously cached token if we have one (spotipy auto-refreshes
    # it), so we only do the browser login the first time.
    if not auth_manager.cache_handler.get_cached_token():
        # Start local callback server
        _server = HTTPServer(("0.0.0.0", PORT), CallbackHandler)
        server_thread = threading.Thread(target=_server.serve_forever)
        server_thread.daemon = True
        server_thread.start()
        print(f"🔌  Callback server listening on port {PORT}")

        # Open Spotify login in browser
        auth_url = auth_manager.get_authorize_url()
        print("🌐  Opening Spotify login…\n")
        webbrowser.open(auth_url)

        # Wait for callback
        print("⏳  Waiting for Spotify callback (60s timeout)…")
        for _ in range(60):
            if _auth_code["value"]:
                break
            time.sleep(1)
        else:
            print("❌  Timed out. Make sure the redirect URI matches exactly.")
            return

        # Exchange code → token
        auth_manager.get_access_token(_auth_code["value"], as_dict=False)

    sp = spotipy.Spotify(auth_manager=auth_manager)
    print("✅  Authenticated!\n")
    filter_name = sys.argv[1] if len(sys.argv) > 1 else "."
    export(sp, OUTPUT_FILE, filter_name)


if __name__ == "__main__":
    main()