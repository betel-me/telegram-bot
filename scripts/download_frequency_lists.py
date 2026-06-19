"""
Download German word-frequency data used for CEFR-level word ranking.

Source: hermitdave/FrequencyWords (CC-BY-SA 4.0)
https://github.com/hermitdave/FrequencyWords

Run once before starting the bot:
    python scripts/download_frequency_lists.py
"""

import os
import urllib.request

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

FILES = {
    "de_50k.txt": "https://raw.githubusercontent.com/hermitdave/FrequencyWords/master/content/2018/de/de_50k.txt",
    # Add more languages here as needed, e.g.:
    # "en_50k.txt": "https://raw.githubusercontent.com/hermitdave/FrequencyWords/master/content/2018/en/en_50k.txt",
}


def download():
    os.makedirs(DATA_DIR, exist_ok=True)

    for filename, url in FILES.items():
        dest = os.path.join(DATA_DIR, filename)
        if os.path.exists(dest):
            print(f"✅ {filename} already exists, skipping.")
            continue

        print(f"⬇️  Downloading {filename} ...")
        try:
            urllib.request.urlretrieve(url, dest)
            print(f"✅ Saved to {dest}")
        except Exception as e:
            print(f"❌ Failed to download {filename}: {e}")
            print("   You can manually download it from:")
            print(f"   {url}")
            print(f"   and save it to: {dest}")


if __name__ == "__main__":
    download()