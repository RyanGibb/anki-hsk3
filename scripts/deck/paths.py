"""Where the build reads from and writes to."""
import os
import pathlib


ROOT = pathlib.Path(__file__).resolve().parents[2]
BUILD = ROOT / "build"
MEDIA = BUILD / "media"
RAW = ROOT / "data/raw"
MMAH_DICT = pathlib.Path(
    os.environ.get("MAKEMEAHANZI", "~/projects/makemeahanzi")
).expanduser() / "dictionary.txt"


TPL = ROOT / "templates"
