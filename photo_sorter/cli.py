"""
Command-line interface for the photo sorter.
Orchestrates EXIF reading, location matching, and file operations.

Copyright (c) 2026 Benjoe Vidal
Licensed under the MIT License.
"""

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional

from .config import load_config, SorterConfig
from .exif_reader import get_gps_from_image, is_image_file
from .file_ops import copy_image, move_image
from .geocode import (
    cluster_key,
    cluster_precision_from_radius_km,
    get_place_name,
    rounded_coords_folder_name,
    sanitize_folder_name,
    to_single_word_english,
)
from .location_matcher import match_location


def setup_logging(verbose: bool) -> None:
    """Configure logging level and format."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        stream=sys.stdout,
    )


def run(
    input_dir: str | Path,
    output_dir: str | Path,
    config: SorterConfig,
    move: bool = False,
    verbose: bool = False,
    geocode: bool = False,
    geocode_cache_path: Optional[Path] = None,
    cluster_radius_km: float = 10.0,
    single_word_english: bool = True,
) -> dict:
    """
    Run the photo sorter: scan input_dir for images, match by GPS, copy or move
    into output_dir under location-named folders.

    When config has no locations (auto mode), photos are grouped by proximity
    (cluster_radius_km) and folder names are single-word English (e.g. SJDMBulacan,
    QuezonCityUP) unless single_word_english=False.

    Returns a summary dict: total, sorted, skipped_no_gps, skipped_no_match_left,
    skipped_other, errors (list of (path, error_message)).
    """
    log = logging.getLogger(__name__)
    input_path = Path(input_dir)
    base_output = Path(output_dir)

    if not input_path.is_dir():
        raise NotADirectoryError(f"Input is not a directory: {input_path}")

    # Resolve output: config.base_output can override if output_dir was not explicitly set
    # Here we always use the CLI output_dir as the base
    base_output = base_output.resolve()
    base_output.mkdir(parents=True, exist_ok=True)

    total = 0
    sorted_count = 0
    skipped_no_gps = 0
    skipped_no_match = 0
    skipped_left_in_place = 0
    errors: list[tuple[Path, str]] = []

    # Gather image files (one level or recursive? — common to do recursive for "many images")
    image_paths = [
        p for p in input_path.rglob("*")
        if p.is_file() and is_image_file(p)
    ]
    total = len(image_paths)

    if total == 0:
        log.info("No image files found in %s", input_path)
        return {
            "total": 0,
            "sorted": 0,
            "skipped_no_gps": 0,
            "skipped_no_match_left": 0,
            "skipped_other": 0,
            "errors": [],
        }

    auto_mode = len(config.locations) == 0
    if auto_mode:
        if geocode:
            log.info(
                "Geocoding: ON (Nominatim/OpenStreetMap — no API key required). Folder names will be place names."
            )
            if geocode_cache_path is None:
                log.error("Geocoding is ON but no cache path set. Place names may not work.")
            else:
                log.info("Cache file: %s (delete this file if you keep getting Lat/Lon folder names)", geocode_cache_path)
        else:
            log.warning(
                "Geocoding: OFF. Folders will be named by coordinates (e.g. Lat25_03Lon121_56). Use --geocode for place names (no API key needed)."
            )
        log.info(
            "Auto mode: grouping by location (radius %s km), folder names: %s.",
            cluster_radius_km,
            "single-word English" + (" (geocoded)" if geocode else " (coordinates)") if single_word_english else "as-is",
        )
    log.info("Processing %d image(s) from %s", total, input_path)
    do_move = move
    uncategorized_behavior = config.uncategorized_behavior
    uncategorized_name = config.uncategorized_folder_name

    if auto_mode:
        # Two-phase: collect (path, lat, lon), group by cluster, then resolve folder names and copy/move
        from collections import defaultdict
        cluster_precision = cluster_precision_from_radius_km(cluster_radius_km)
        cluster_to_paths: dict[tuple[float, float], list[tuple[Path, float, float]]] = defaultdict(list)
        no_gps_paths: list[Path] = []  # Collect images without GPS
        
        for path in image_paths:
            try:
                gps = get_gps_from_image(path)
                if gps is None:
                    no_gps_paths.append(path)
                    if verbose:
                        log.debug("No GPS: %s", path.name)
                    continue
                lat, lon = gps
                if verbose:
                    log.debug("GPS extracted from %s: lat=%.6f, lon=%.6f", path.name, lat, lon)
                center = cluster_key(lat, lon, cluster_radius_km)
                cluster_to_paths[center].append((path, lat, lon))
            except Exception as e:
                errors.append((path, str(e)))
                if verbose:
                    log.debug("Error extracting GPS from %s: %s", path.name, e)
        
        # Move images without GPS to "Skipped" folder
        if no_gps_paths:
            skipped_folder_name = "Skipped" if single_word_english else "Skipped"
            skipped_dir = base_output / skipped_folder_name
            for path in no_gps_paths:
                try:
                    if do_move:
                        move_image(path, skipped_dir)
                    else:
                        copy_image(path, skipped_dir)
                    skipped_no_gps += 1
                    sorted_count += 1  # Count as sorted (moved to Skipped folder)
                    if verbose:
                        log.debug("No GPS: %s -> Skipped", path.name)
                except Exception as e:
                    errors.append((path, str(e)))
                    if verbose:
                        log.debug("Error moving no-GPS file %s: %s", path.name, e)

        # Resolve folder name per cluster: use ACTUAL photo coordinates for geocoding
        # (not the rounded cluster center), so Nominatim returns the real place name.
        cluster_to_folder: dict[tuple[float, float], str] = {}
        geocode_failures = 0
        if geocode and geocode_cache_path is not None and cluster_to_paths:
            log.info("Resolving place names for %d location(s) from Nominatim (this may take a moment)...", len(cluster_to_paths))
        for (lat_c, lon_c), paths in cluster_to_paths.items():
            if verbose:
                log.debug("Processing cluster (%.6f, %.6f) with %d photo(s)", lat_c, lon_c, len(paths))
            # Use first photo's actual (lat, lon) for geocoding - real coordinates give real place names
            lat_actual, lon_actual = paths[0][1], paths[0][2]
            if geocode and geocode_cache_path is not None:
                folder_name = get_place_name(
                    lat_actual,
                    lon_actual,
                    cache_path=geocode_cache_path,
                    use_network=True,
                    single_word_english=single_word_english,
                    cache_precision=cluster_precision,  # cache key still by cluster to avoid duplicate API calls
                )
                if verbose:
                    log.debug("Geocoded (%.6f, %.6f) -> folder name: %s", lat_actual, lon_actual, folder_name)
                # Check if geocoding failed (returned coordinate-based fallback or "Unknown")
                if single_word_english and (folder_name.startswith("Lat") and "Lon" in folder_name or folder_name == "Unknown"):
                    geocode_failures += 1
                    if verbose:
                        log.debug("Geocoding failed for (%.6f, %.6f), using coordinate name: %s", lat_actual, lon_actual, folder_name)
                    # Replace "Unknown" with coordinate fallback
                    if folder_name == "Unknown":
                        folder_name = rounded_coords_folder_name(lat_c, lon_c, single_word_english=single_word_english)
                        safe_folder_name = sanitize_folder_name(folder_name)
                        cluster_to_folder[(lat_c, lon_c)] = safe_folder_name
            else:
                folder_name = rounded_coords_folder_name(lat_c, lon_c, single_word_english=single_word_english)
            safe_folder_name = sanitize_folder_name(folder_name)
            cluster_to_folder[(lat_c, lon_c)] = safe_folder_name
        
        if geocode and geocode_failures > 0:
            log.error(
                "⚠️  Geocoding failed for %d location(s). Using coordinate-based folder names.\n"
                "   Fix: 1) Delete the cache file shown at the start (in your output folder)\n"
                "        2) Check your internet connection\n"
                "        3) Run again: photo-sorter -i ... -o ... (geocoding is on by default)\n"
                "        4) If it still fails, run with --verbose to see errors.",
                geocode_failures
            )
        elif not geocode:
            log.warning(
                "⚠️  Geocoding is OFF. To get place names, run without --no-geocode: photo-sorter -i ... -o ..."
            )

        for (lat_c, lon_c), paths in cluster_to_paths.items():
            safe_folder_name = cluster_to_folder[(lat_c, lon_c)]
            dest_dir = base_output / safe_folder_name
            for path, _lat, _lon in paths:
                try:
                    if do_move:
                        move_image(path, dest_dir)
                    else:
                        copy_image(path, dest_dir)
                    sorted_count += 1
                    if verbose:
                        log.debug("Sorted: %s -> %s", path.name, safe_folder_name)
                except Exception as e:
                    errors.append((path, str(e)))

    else:
        # Config mode: match each photo to a location, apply single-word naming to config names if requested
        skipped_folder_name = "Skipped" if single_word_english else "Skipped"
        skipped_dir = base_output / skipped_folder_name
        
        for path in image_paths:
            try:
                gps = get_gps_from_image(path)
                if gps is None:
                    # Move to Skipped folder
                    try:
                        if do_move:
                            move_image(path, skipped_dir)
                        else:
                            copy_image(path, skipped_dir)
                        skipped_no_gps += 1
                        sorted_count += 1  # Count as sorted (moved to Skipped folder)
                        if verbose:
                            log.debug("No GPS: %s -> Skipped", path.name)
                    except Exception as e:
                        errors.append((path, str(e)))
                        if verbose:
                            log.debug("Error moving no-GPS file %s: %s", path.name, e)
                    continue

                lat, lon = gps
                folder_name = match_location(lat, lon, config)

                if folder_name is None:
                    if uncategorized_behavior == "leave_in_place":
                        skipped_left_in_place += 1
                        if verbose:
                            log.debug("No match, left in place: %s", path.name)
                    else:
                        dest_dir = base_output / sanitize_folder_name(uncategorized_name)
                        if do_move:
                            move_image(path, dest_dir)
                        else:
                            copy_image(path, dest_dir)
                        sorted_count += 1
                        if verbose:
                            log.debug("Uncategorized: %s -> %s", path.name, uncategorized_name)
                    continue

                if single_word_english:
                    folder_name = to_single_word_english(folder_name)
                safe_folder_name = sanitize_folder_name(folder_name) if not single_word_english else folder_name
                dest_dir = base_output / safe_folder_name
                if do_move:
                    move_image(path, dest_dir)
                else:
                    copy_image(path, dest_dir)
                sorted_count += 1
                if verbose:
                    log.debug("Sorted: %s -> %s", path.name, safe_folder_name)

            except Exception as e:
                errors.append((path, str(e)))

    skipped_other = total - sorted_count - skipped_no_gps - skipped_left_in_place - len(errors)
    if skipped_other < 0:
        skipped_other = 0

    # Summary
    log.info("--- Summary ---")
    log.info("Total images: %d", total)
    log.info("Sorted (copy/move): %d", sorted_count)
    if skipped_no_gps > 0:
        log.info("No GPS (moved to 'Skipped' folder): %d", skipped_no_gps)
    if uncategorized_behavior == "leave_in_place":
        log.info("Skipped (no match, left in place): %d", skipped_left_in_place)
    log.info("Errors: %d", len(errors))
    for p, err in errors:
        log.warning("  %s: %s", p.name, err)

    return {
        "total": total,
        "sorted": sorted_count,
        "skipped_no_gps": skipped_no_gps,
        "skipped_no_match_left": skipped_left_in_place,
        "skipped_other": skipped_other,
        "errors": errors,
    }


def main(argv: Optional[list[str]] = None) -> int:
    """Parse arguments, load config, and run the sorter. Return exit code."""
    parser = argparse.ArgumentParser(
        description="Sort photos into folders by GPS coordinates from EXIF.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--input", "-i",
        required=True,
        help="Source directory containing images.",
    )
    parser.add_argument(
        "--output", "-o",
        required=True,
        help="Base output directory for sorted folders.",
    )
    parser.add_argument(
        "--config", "-c",
        default=None,
        help="Path to locations config (JSON or YAML). If omitted, folders are named by coordinates or by --geocode.",
    )
    parser.add_argument(
        "--geocode",
        action="store_true",
        default=True,
        help="Resolve folder names via reverse geocoding (Nominatim). Default: ON. No API key required.",
    )
    parser.add_argument(
        "--no-geocode",
        action="store_false",
        dest="geocode",
        help="Disable geocoding; use coordinate-based folder names (e.g. Lat25_03Lon121_56).",
    )
    parser.add_argument(
        "--geocode-cache",
        default=None,
        metavar="PATH",
        help="Path to geocode cache file (default: photo_sorter_geocode_cache.json in output dir).",
    )
    parser.add_argument(
        "--cluster-radius-km",
        type=float,
        default=10.0,
        metavar="KM",
        help="In auto mode, put photos within this distance in the same folder (default: 10).",
    )
    parser.add_argument(
        "--no-single-word",
        action="store_true",
        help="Use original folder names (spaces allowed). Default is single-word English .",
    )
    parser.add_argument(
        "--move",
        action="store_true",
        help="Move files instead of copying (default: copy).",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose logging.",
    )

    args = parser.parse_args(argv)

    setup_logging(args.verbose)

    if args.config is not None:
        try:
            config = load_config(args.config)
        except FileNotFoundError as e:
            logging.error("%s", e)
            return 1
        except ValueError as e:
            logging.error("Invalid config: %s", e)
            return 1
    else:
        config = SorterConfig()

    geocode_cache_path = None
    if args.geocode:
        if args.geocode_cache:
            geocode_cache_path = Path(args.geocode_cache)
        else:
            geocode_cache_path = Path(args.output).resolve() / "photo_sorter_geocode_cache.json"

    try:
        run(
            input_dir=args.input,
            output_dir=args.output,
            config=config,
            move=args.move,
            verbose=args.verbose,
            geocode=args.geocode,
            geocode_cache_path=geocode_cache_path,
            cluster_radius_km=args.cluster_radius_km,
            single_word_english=not args.no_single_word,
        )
    except NotADirectoryError as e:
        logging.error("%s", e)
        return 1
    except Exception as e:
        logging.exception("Unexpected error: %s", e)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
