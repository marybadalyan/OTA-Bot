import csv
import json
import os
import subprocess
import sys
import tempfile
import shutil

OUTPUT_DIR = "playlists"
BITRATE = "128K"
IMG_W = 128
IMG_H = 48


def safe_name(artist, song):
    name = f"{artist} - {song}"
    return "".join(c if c not in r'\/:*?"<>|' else "_" for c in name)


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


filter_playlist = sys.argv[1] if len(sys.argv) > 1 else "."

for playlist in sorted(os.listdir(OUTPUT_DIR)):
    if filter_playlist != "." and playlist != filter_playlist:
        continue
    folder = os.path.join(OUTPUT_DIR, playlist)
    tracks_file = os.path.join(folder, "tracks.csv")
    if not os.path.isfile(tracks_file):
        continue

    print(f"=== {playlist} ===")
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
            print(f"  [skip]     {artist} - {song}  (no URL in tracks.csv)")
            continue

        if os.path.exists(dest_mp3) and os.path.exists(dest_jpg):
            print(f"  [skip]     {artist} - {song}  (already downloaded)")
            mapping.append({"mp3": name + ".mp3", "jpg": name + ".jpg", "artist": artist, "song": song})
            continue

        print(f"  [download] {artist} - {song} ...", end=" ", flush=True)
        try:
            fetch_track(url, dest_mp3, dest_jpg)
            print("done")
            mapping.append({"mp3": name + ".mp3", "jpg": name + ".jpg", "artist": artist, "song": song})
        except Exception as e:
            print(f"FAILED: {e}")

    with open(os.path.join(folder, "mapping.json"), "w", encoding="utf-8") as f:
        json.dump(mapping, f, indent=2, ensure_ascii=False)

    print(f"  → mapping.json updated\n")

print("Done.")
