#!/usr/bin/env python3
"""optimize_hotel_images.py -- reusable image pipeline for the hotel
photography portfolio section.

For every input image this script produces two JPEG outputs:

  Full  -> img/hotels/<category>-NN.jpg          (max edge 1800px, quality 82)
  Thumb -> img/hotels/thumbs/<category>-NN.jpg    (max edge  800px, quality 72)

Both outputs are progressive, Pillow-optimized JPEGs, converted to RGB
(RGBA/PNG/CMYK/grayscale sources are handled -- transparency is composited
onto a white background). EXIF orientation is applied before resizing so
rotated phone/camera shots come out right-side-up, and ALL EXIF metadata
(including GPS coordinates and camera serial numbers) is stripped from the
saved files -- nothing is ever passed via an `exif=` kwarg on save.

HEIC/HEIF support: iPhone photos exported from Google Drive are commonly
in HEIC/HEIF format, which plain Pillow cannot open. If the optional
`pillow-heif` package is installed, its HEIF opener is registered with
Pillow at import time, and `.heic`/`.heif` files are handled exactly like
any other input (orientation applied, EXIF/GPS stripped). Install it with:

    pip install pillow-heif

If `pillow-heif` is not installed, JPEG/PNG inputs are unaffected, but any
`.heic`/`.heif` input file is skipped with a message telling you to install
`pillow-heif` rather than failing with a confusing generic Pillow error.

`NN` is a zero-padded 2-digit counter that is auto-numbered per category:
by default the script continues from the highest `<category>-NN.jpg`
already present in img/hotels/, so re-running the script with new files
appends to the category instead of overwriting existing photos.

Usage
-----
    python3 tools/optimize_hotel_images.py <category> <file1> [file2 ...] [--start N] [--dry-run]

Categories (exactly these 10 ids):
    arrival, common, rooms, bath, spa, pool, gastronomy, details,
    experience, destination

Examples
--------
Add the first batch of arrival photos (auto-numbered starting at 01):

    python3 tools/optimize_hotel_images.py arrival lobby1.jpg lobby2.jpg

Add more photos to the same category later -- numbering continues
automatically from the highest existing arrival-NN.jpg (e.g. arrival-03,
arrival-04, ...):

    python3 tools/optimize_hotel_images.py arrival new_lobby_shot.jpg

Force a specific starting number instead of auto-continuing:

    python3 tools/optimize_hotel_images.py rooms room_a.jpg room_b.jpg --start 5

Preview what would happen without writing any files:

    python3 tools/optimize_hotel_images.py spa spa_pool.jpg --dry-run
"""

import argparse
import os
import re
import sys

from PIL import Image, ImageOps

try:
    import pillow_heif

    pillow_heif.register_heif_opener()
    HEIF_SUPPORT = True
except ImportError:
    HEIF_SUPPORT = False

HEIF_EXTENSIONS = (".heic", ".heif")

VALID_CATEGORIES = (
    "arrival",
    "common",
    "rooms",
    "bath",
    "spa",
    "pool",
    "gastronomy",
    "details",
    "experience",
    "destination",
)

FULL_MAX_EDGE = 1800
FULL_QUALITY = 82
THUMB_MAX_EDGE = 800
THUMB_QUALITY = 72

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMG_DIR = os.path.join(REPO_ROOT, "img", "hotels")
THUMBS_DIR = os.path.join(IMG_DIR, "thumbs")


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Optimize hotel photography into full + thumbnail JPEGs.",
    )
    parser.add_argument(
        "category",
        help="One of: " + ", ".join(VALID_CATEGORIES),
    )
    parser.add_argument(
        "files",
        nargs="+",
        help="Input image file paths.",
    )
    parser.add_argument(
        "--start",
        type=int,
        default=None,
        help="Force the starting NN counter instead of auto-continuing "
        "from the highest existing <category>-NN.jpg.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the planned input->output mapping and exit without writing.",
    )
    return parser.parse_args(argv)


def validate_category(category):
    if category not in VALID_CATEGORIES:
        sys.stderr.write(
            "Error: invalid category '%s'.\nValid category ids are: %s\n"
            % (category, ", ".join(VALID_CATEGORIES))
        )
        sys.exit(2)


def highest_existing_number(category):
    """Return the highest NN found in img/hotels/<category>-NN.jpg, or 0."""
    if not os.path.isdir(IMG_DIR):
        return 0
    pattern = re.compile(r"^%s-(\d{2,})\.jpg$" % re.escape(category))
    highest = 0
    for name in os.listdir(IMG_DIR):
        match = pattern.match(name)
        if match:
            highest = max(highest, int(match.group(1)))
    return highest


def kb(num_bytes):
    return num_bytes / 1024.0


def load_and_orient(path):
    """Open an image, apply EXIF orientation, and return an RGB copy with
    no EXIF metadata attached (transparency is composited onto white)."""
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im)  # applies, then drops, the orientation tag

        if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
            im = im.convert("RGBA")
            background = Image.new("RGB", im.size, (255, 255, 255))
            background.paste(im, mask=im.split()[-1])
            rgb = background
        else:
            rgb = im.convert("RGB")

        # convert()/transpose() carry the source's .info dict (exif, icc
        # profile, dpi, ...) forward. Clear it explicitly so nothing --
        # GPS coordinates, camera serial numbers, anything -- survives
        # into the output, even though we also never pass exif= on save.
        rgb.info = {}
        return rgb


def resize_to_max_edge(im, max_edge):
    width, height = im.size
    longest = max(width, height)
    if longest <= max_edge:
        return im  # never upscale
    scale = max_edge / float(longest)
    new_size = (max(1, round(width * scale)), max(1, round(height * scale)))
    return im.resize(new_size, Image.Resampling.LANCZOS)


def save_jpeg(im, path, quality):
    im.save(
        path,
        format="JPEG",
        quality=quality,
        progressive=True,
        optimize=True,
    )


def process_one(src_path, category, number, dry_run):
    basename = os.path.basename(src_path)
    out_name = "%s-%02d.jpg" % (category, number)
    full_path = os.path.join(IMG_DIR, out_name)
    thumb_path = os.path.join(THUMBS_DIR, out_name)

    if not os.path.isfile(src_path):
        print("SKIP  %-30s -> (missing/unreadable input file)" % basename)
        return False

    if os.path.splitext(basename)[1].lower() in HEIF_EXTENSIONS and not HEIF_SUPPORT:
        print(
            "SKIP  %-30s -> (HEIC/HEIF input requires the 'pillow-heif' package; "
            "install it with: pip install pillow-heif)" % basename
        )
        return False

    try:
        original_bytes = os.path.getsize(src_path)
        im = load_and_orient(src_path)
    except Exception as exc:
        print("SKIP  %-30s -> (failed to read image: %s)" % (basename, exc))
        return False

    orig_w, orig_h = im.size

    if dry_run:
        print(
            "DRY-RUN  %s -> %s (%dx%d) / %s"
            % (basename, full_path, orig_w, orig_h, thumb_path)
        )
        return True

    try:
        full_im = resize_to_max_edge(im, FULL_MAX_EDGE)
        thumb_im = resize_to_max_edge(im, THUMB_MAX_EDGE)

        save_jpeg(full_im, full_path, FULL_QUALITY)
        save_jpeg(thumb_im, thumb_path, THUMB_QUALITY)
    except Exception as exc:
        print("SKIP  %-30s -> (failed to process/save: %s)" % (basename, exc))
        return False

    full_bytes = os.path.getsize(full_path)
    thumb_bytes = os.path.getsize(thumb_path)

    print(
        "%-24s -> %-22s  %4dx%-4d -> full %4dx%-4d / thumb %4dx%-4d   "
        "orig %6.1fKB -> full %6.1fKB / thumb %6.1fKB"
        % (
            basename,
            out_name,
            orig_w,
            orig_h,
            full_im.size[0],
            full_im.size[1],
            thumb_im.size[0],
            thumb_im.size[1],
            kb(original_bytes),
            kb(full_bytes),
            kb(thumb_bytes),
        )
    )
    return True


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    validate_category(args.category)

    if not args.dry_run:
        os.makedirs(IMG_DIR, exist_ok=True)
        os.makedirs(THUMBS_DIR, exist_ok=True)

    start = args.start if args.start is not None else highest_existing_number(args.category) + 1

    any_failed = False
    number = start
    for src_path in args.files:
        ok = process_one(src_path, args.category, number, args.dry_run)
        if not ok:
            any_failed = True
            continue  # do not consume a number for a failed/skipped file
        number += 1

    if any_failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
