# Photo Sorter

A desktop tool that sorts photos into folders based on **GPS coordinates** from EXIF. Use it **with no config** and optional **reverse geocoding** so folder names are chosen for you, or provide a config file for full control.

## Features

- **Single-word English folder names**: By default, folder names are one word, English only (e.g. `Taiwan101`, `YehliuGeopark`, `TokyoJapan`). Non-ASCII is transliterated. Use `--no-single-word` to keep original names with spaces.
- **Nearby photos in one folder**: In auto mode, photos within a configurable distance (default 10 km) are grouped into the same folder. Use `--cluster-radius-km` to change this.
- **Zero-config option**: Run without a config file. Photos are grouped by proximity; folder names are single-word (coordinates or place names with `--geocode`).
- **Optional reverse geocoding**: `--geocode` looks up place names and converts them to single-word English. Results are **cached locally**, so later runs stay fast and work offline.
- **EXIF GPS**: Reads latitude/longitude from JPEG, PNG, HEIC (optional), TIFF.
- **Optional config**: Define your own locations (point + radius or bounding box). Config names are converted to single-word English by default.
- **Safe by default**: **Copies** files unless you pass `--move`.
- **Uncategorized handling**: Put photos with no match into an "Uncategorized" folder, or leave them in place (configurable).
- **No overwrites**: If a file with the same name exists, the tool adds a suffix like `(1)`, `(2)`.
- **CLI**: Simple arguments, clear logging and summary.

## Requirements

- **Python 3.10+**
- Dependencies: Pillow, piexif, PyYAML (see below).

## Installation

### 1. Clone or copy the project

```bash
cd c:\..\Documents\sorter
```

### 2. Create a virtual environment (recommended)

```bash
python -m venv .venv
.venv\Scripts\activate   # Windows
# source .venv/bin/activate   # macOS/Linux
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

Optional: for **HEIC** (iPhone) support:

```bash
pip install pillow-heif
```

### 4. Install the package (so you can run `photo-sorter` from anywhere)

```bash
pip install -e .
```

Or run without installing:

```bash
python -m photo_sorter --input ... --output ... --config ...
```

## Usage

### Recommended: zero effort (no config, automatic place names)

**No API key required.** Geocoding is **on by default**. Folder names come from Nominatim (OpenStreetMap) and are single-word English (e.g. `CebuKawasanFalls`, `IlocosNorte`). Photos within 10 km are grouped into the same folder.

```bash
photo-sorter -i "C:\path\to\photos" -o "C:\path\to\sorted"
```

You should see: `Geocoding: ON (Nominatim/OpenStreetMap — no API key required).`

**First run**: May be slower (one request per unique area, ~1/sec). **Later runs**: Use the cache and are fast and offline. If you still see `Lat25_03Lon121_56`-style names, check your internet connection, delete the cache file (`photo_sorter_geocode_cache.json`) in the output folder, and run again.

### Coordinate-based folders (no internet)

To use coordinate folder names instead of place names (fully offline), turn off geocoding:

```bash
photo-sorter -i "C:\path\to\photos" -o "C:\path\to\sorted" --no-geocode
```

### With a config file (full control)

When you want specific locations and custom folder names:

```bash
photo-sorter -i "C:\Users\Me\Pictures\Trip" -o "C:\Users\Me\Pictures\Sorted" -c "locations.json"
```

### Options

| Option | Short | Description |
|--------|--------|-------------|
| `--input` | `-i` | **Required.** Source directory containing images. |
| `--output` | `-o` | **Required.** Base output directory for sorted folders. |
| `--config` | `-c` | Optional. Path to locations config (JSON or YAML). If omitted, folders are named by coordinates or by `--geocode`. |
| `--geocode` | | Use place names for folders (default: ON). Uses Nominatim — no API key. |
| `--no-geocode` | | Use coordinate folder names (e.g. Lat25_03Lon121_56) instead of place names. |
| `--geocode-cache` | | Path to geocode cache file (default: `photo_sorter_geocode_cache.json` in output dir). |
| `--cluster-radius-km` | | In auto mode, put photos within this distance (km) in the same folder. Default: 10. |
| `--no-single-word` | | Allow spaces in folder names. Default is single-word English only (e.g. LunetaPark, NationalMuseum). |
| `--move` | | Move files instead of copying (default: copy). |
| `--verbose` | `-v` | Log each file decision. |

### Examples

**Best UX — no config, automatic place names:**

```bash
photo-sorter -i "D:\Photos\2024" -o "D:\Photos\ByLocation" --geocode
```

**No config, fully offline (folders named by coordinates):**

```bash
photo-sorter -i "D:\Photos\2024" -o "D:\Photos\ByLocation"
```

**With config and geocoding (config locations used first; geocode can still name uncategorized areas):**

```bash
photo-sorter -i "D:\Photos\2024" -o "D:\Photos\ByLocation" -c "locations.json" --geocode
```

**Move instead of copy:**

```bash
photo-sorter -i "D:\Photos\2024" -o "D:\Photos\ByLocation" --geocode --move
```

**Using the example config:**

```bash
photo-sorter -i "./my_photos" -o "./sorted_photos" -c "locations.example.json"
```

## Config file (optional)

Use **JSON** or **YAML** when you want to define specific locations and folder names. Path: any file you pass to `--config`. You can skip the config and use auto mode (coordinates or `--geocode`) instead.

### Structure

| Field | Type | Description |
|-------|------|-------------|
| `base_output` | string | Optional. Can be overridden by `--output` (CLI takes precedence in this implementation). |
| `uncategorized_behavior` | string | `"folder"` (default) or `"leave_in_place"`. |
| `uncategorized_folder_name` | string | Name of folder for non-matching photos when behavior is `"folder"`. Default: `"Uncategorized"`. |
| `match_radius_km` | number | Default radius in km for point locations that don’t specify `radius_km`. Default: `0.5`. |
| `locations` | array | List of location objects (see below). |

Use **single-word English** names in the config (e.g. `Taiwan101`, `YehliuGeopark`, `TokyoJapan`). If you use spaces (e.g. "Shifen Old Street"), the tool converts them to single-word by default (e.g. `ShifenOldStreet`) unless you pass `--no-single-word`.

### Location types

**1. Point + radius** (nearest within radius)

```json
{
  "name": "Manila",
  "point": { "lat": 25.0339, "lon": 121.5645 },
  "radius_km": 0.3
}
```

Or using `center` (same idea):

```json
{
  "name": "Binondo",
  "center": { "lat": 25.2878, "lon": 121.6906 },
  "radius_km": 0.5
}
```

**2. Bounding box** (inside rectangle; good for grouping nearby areas like Jiufen + Shifen)

```json
{
  "name": "Luneta",
  "bounds": {
    "min_lat": 25.04,
    "max_lat": 25.12,
    "min_lon": 121.76,
    "max_lon": 121.85
  }
}
```

### Example config

See **`locations.example.json`** in the project root. It defines three locations (Taipei 101, Shifen Old Street, Jiufen) and uncategorized behavior.

## Output layout

Under the directory you pass to `--output`, the tool creates one folder per location (single-word English by default) and (if configured) an uncategorized folder:

```
/output/
  Davao/
    IMG_001.jpg
    IMG_002.jpg
  SamalIsland/
    IMG_003.jpg
  GovGen/
    IMG_004.jpg
  Skipped/
    IMG_005.jpg   (no GPS in EXIF)
  Uncategorized/
    IMG_006.jpg   (GPS found but no matching location in config)
```

Duplicate names get a suffix: `IMG_001 (1).jpg`, etc.

**Note**: Images without GPS are automatically moved/copied to a `Skipped` folder. Images with GPS that don't match any location (in config mode) go to `Uncategorized` (or are left in place if configured).

## Logging and summary

The tool prints:

- How many images were found and processed.
- How many were **sorted** (copy or move) and into which folders.
- How many had **no GPS** (moved to `Skipped` folder).
- How many were **left in place** (if `uncategorized_behavior` is `"leave_in_place"` and they didn’t match).
- Any **errors** (e.g. read/write failures) with file names and messages.

Use `--verbose` to see per-file decisions.

## Robustness

- **No EXIF / no GPS**: Image is moved/copied to `Skipped` folder; the run continues.
- **Corrupt EXIF**: Treated as no GPS; no crash.
- **Per-file errors**: One bad file does not stop the whole run; errors are reported in the summary.
- **Default is copy**: Originals are kept unless you use `--move`.

## Running tests

From the project root:

```bash
pip install -r requirements.txt
pytest tests/ -v
```

Tests cover:

- EXIF parsing and GPS extraction (including a JPEG with embedded GPS).
- Location matching (bounds, point+radius, nearest).
- Config loading (point, bounds, uncategorized options).
- File operations (copy, move, unique names in a temp directory).

## Project layout

```
sorter/
  photo_sorter/
    __init__.py
    __main__.py      # python -m photo_sorter
    cli.py           # CLI and orchestration
    config.py        # Load/validate JSON or YAML config
    exif_reader.py   # EXIF GPS extraction
    geocode.py       # Optional reverse geocoding (cache + Nominatim)
    location_matcher.py  # Match (lat, lon) to locations
    file_ops.py      # Copy/move and unique paths
  tests/
    test_exif_reader.py
    test_location_matcher.py
    test_file_ops.py
    test_config.py
  locations.example.json
  requirements.txt
  pyproject.toml
  README.md
```

## Reverse geocoding (default on)

**You do not need an API key.** The tool uses Nominatim (OpenStreetMap), which is free. Geocoding is **on by default** so you get place names (e.g. Binondo, LunetaPark) unless you pass `--no-geocode`. Results are cached in the output dir; first run does one request per area (~1/sec), later runs use the cache and work offline.

**Troubleshooting:**
- **Numeric folder names (like `32054`)**: The geocoding API may have returned a postal code, or your cache has bad values. The tool now automatically filters these out. **Solution**: Delete the cache file (`photo_sorter_geocode_cache.json` in your output directory) and run again.
- **Coordinate names (`Lat25_03Lon121_56`)**: Geocoding failed. Check your internet connection or try again later. Use `--verbose` to see detailed GPS extraction and geocoding logs.
- **GPS not found**: Make sure your photos have GPS EXIF data. Use `--verbose` to see which photos are being skipped.
- **Cache issues**: You can manually edit the cache file (`photo_sorter_geocode_cache.json`) to fix or override folder names, or delete it to force fresh geocoding.
- Use `--geocode-cache` to set a custom cache path.
- **Where is the cache?** It’s in the **output folder** you pass to `-o`, e.g. `C:\Users\You\Documents\sortsort\photo_sorter_geocode_cache.json`. It’s a normal file (no leading dot), so it’s visible in File Explorer.

Config-based folder names still take precedence when you use a config file. Cached names are used in auto mode.

## License

Copyright (c) 2026 Benjoe Vidal

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Contributing

Contributions are welcome! Feel free to open issues or submit pull requests.

buymeacoffee.com/benjoe22d
