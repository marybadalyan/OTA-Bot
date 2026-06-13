import csv
import json
import os
import subprocess
import tempfile
import shutil
import sys

CSV_FILE = "spotify_playlists.csv"
OUTPUT_DIR = "playlists"
BITRATE = "128K"
IMG_W = 128
IMG_H = 48


def youtube_search(artist, song):
    result = subprocess.run(
        ["yt-dlp", "--no-download", "--print", "webpage_url", f"ytsearch1:{artist} {song}"],
        capture_output=True, text=True,
    )
    url = result.stdout.strip()
    return url if url.startswith("https://") else None


def fetch_track(url, dest_mp3, dest_jpg):
    with tempfile.TemporaryDirectory() as tmp:
        result = subprocess.run([
            "yt-dlp", "-x", "--audio-format", "mp3", "--audio-quality", BITRATE,
            "--postprocessor-args", "ffmpeg:-ar 44100",
            "--write-thumbnail", "--convert-thumbnails", "jpg",
            "-o", os.path.join(tmp, "track.%(ext)s"),
            url,
        ], capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip().splitlines()[-1] if result.stderr else "yt-dlp failed")

        shutil.copy(os.path.join(tmp, "track.mp3"), dest_mp3)

        thumb = os.path.join(tmp, "track.jpg")
        if not os.path.exists(thumb):
            thumb = os.path.join(tmp, "track.webp")

        result = subprocess.run([
            "ffmpeg", "-y", "-i", thumb,
            "-vf", f"scale={IMG_W}:{IMG_H}:force_original_aspect_ratio=decrease",
            dest_jpg,
        ], capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip().splitlines()[-1] if result.stderr else "ffmpeg failed")


def safe_name(artist, song):
    name = f"{artist} - {song}"
    return "".join(c if c not in r'\/:*?"<>|' else "_" for c in name)


def phase1_search():
    """Read spotify_playlists.csv, search YouTube, write URLs into each playlist's tracks.csv."""
    playlists = {}
    with open(CSV_FILE, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            playlist = row["Playlist"].strip()
            playlists.setdefault(playlist, []).append(
                (row["Artist"].strip(), row["Song"].strip())
            )

    for playlist, tracks in playlists.items():
        folder = os.path.join(OUTPUT_DIR, playlist)
        os.makedirs(folder, exist_ok=True)
        tracks_file = os.path.join(folder, "tracks.csv")

        # Load any URLs already saved so we don't re-search
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
                print(f"  [skip] {artist} - {song}  (URL already set)")
                rows.append((artist, song, existing[key]))
            else:
                print(f"  Searching: {artist} - {song} ...", end=" ", flush=True)
                url = youtube_search(artist, song)
                print(url or "NOT FOUND")
                rows.append((artist, song, url or ""))

        with open(tracks_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Artist", "Song", "YouTube URL"])
            writer.writerows(rows)

        print(f"  → {tracks_file}  (review/edit URLs before downloading)\n")


def phase2_download():
    """Read each playlist's tracks.csv and download mp3+jpg for every row that has a URL."""
    for playlist in os.listdir(OUTPUT_DIR):
        folder = os.path.join(OUTPUT_DIR, playlist)
        tracks_file = os.path.join(folder, "tracks.csv")
        if not os.path.isfile(tracks_file):
            continue

        mapping = []
        with open(tracks_file, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))

        for row in rows:
            artist = row["Artist"].strip()
            song = row["Song"].strip()
            url = row.get("YouTube URL", "").strip()
            name = safe_name(artist, song)
            dest_mp3 = os.path.join(folder, name + ".mp3")
            dest_jpg = os.path.join(folder, name + ".jpg")

            if not url:
                print(f"  [skip] {artist} - {song}  (no URL)")
                continue

            if os.path.exists(dest_mp3) and os.path.exists(dest_jpg):
                print(f"  [skip] {artist} - {song}  (already downloaded)")
                mapping.append({"mp3": name + ".mp3", "jpg": name + ".jpg", "artist": artist, "song": song})
                continue

            print(f"  Downloading: {artist} - {song} ...", end=" ", flush=True)
            try:
                fetch_track(url, dest_mp3, dest_jpg)
                print("done")
                mapping.append({"mp3": name + ".mp3", "jpg": name + ".jpg", "artist": artist, "song": song})
            except Exception as e:
                print(f"FAILED: {e}")

        with open(os.path.join(folder, "mapping.json"), "w", encoding="utf-8") as f:
            json.dump(mapping, f, indent=2, ensure_ascii=False)

        print(f"  → mapping.json updated for '{playlist}'\n")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"

    if mode in ("search", "all"):
        print("=== Phase 1: YouTube search ===")
        phase1_search()

    if mode == "all":
        input("Review/edit tracks.csv files now if needed, then press Enter to start downloading...")

    if mode in ("download", "all"):
        print("=== Phase 2: Downloading ===")
        phase2_download()
