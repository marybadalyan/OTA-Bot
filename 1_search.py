import csv
import os
import subprocess
import sys

CSV_FILE = "spotify_playlists.csv"
OUTPUT_DIR = "playlists"

os.makedirs(OUTPUT_DIR, exist_ok=True)

filter_playlist = sys.argv[1] if len(sys.argv) > 1 else "."


def youtube_search(artist, song):
    result = subprocess.run(
        ["yt-dlp", "--no-download", "--print", "webpage_url", f"ytsearch1:{artist} {song}"],
        capture_output=True, text=True,
    )
    url = result.stdout.strip()
    return url if url.startswith("https://") else None


playlists = {}
with open(CSV_FILE, newline="", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        playlist = row["Playlist"].strip()
        if filter_playlist != "." and playlist != filter_playlist:
            continue
        playlists.setdefault(playlist, []).append(
            (row["Artist"].strip(), row["Song"].strip())
        )

if not playlists:
    print(f"Playlist '{filter_playlist}' not found in CSV.")
    sys.exit(1)

for playlist, tracks in playlists.items():
    folder = os.path.join(OUTPUT_DIR, playlist)
    os.makedirs(folder, exist_ok=True)
    tracks_file = os.path.join(folder, "tracks.csv")

    # keep any URLs already manually set
    existing = {}
    if os.path.exists(tracks_file):
        with open(tracks_file, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                key = (row["Artist"].strip(), row["Song"].strip())
                if row.get("YouTube URL", "").startswith("https://"):
                    existing[key] = row["YouTube URL"].strip()

    rows = []
    for artist, song in tracks:
        key = (artist, song)
        if key in existing:
            print(f"[skip]     {artist} - {song}  (URL already set)")
            rows.append((artist, song, existing[key]))
        else:
            print(f"[search]   {artist} - {song} ...", end=" ", flush=True)
            url = youtube_search(artist, song)
            print(url or "NOT FOUND")
            rows.append((artist, song, url or ""))

    with open(tracks_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Artist", "Song", "YouTube URL"])
        writer.writerows(rows)

    print(f"Saved → {tracks_file}\n")

print("Done.")
