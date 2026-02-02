#!/usr/bin/env python3
"""MTA Train Routing - Find the fastest train to work."""

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

# Use system CA certs (avoids permission issues with sudo)
os.environ.setdefault("REQUESTS_CA_BUNDLE", "/etc/ssl/certs/ca-certificates.crt")

import requests
from google.transit import gtfs_realtime_pb2

# Try to import LED matrix library (only works on Pi)
try:
    from rgbmatrix import RGBMatrix, RGBMatrixOptions, graphics
    HAS_MATRIX = True
except ImportError:
    HAS_MATRIX = False

CONFIG_PATH = Path(__file__).parent / "config.json"
FEED_BASE_URL = "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2F"


@dataclass
class Trip:
    route_name: str
    arrival_at_office: float
    total_min: float
    leave_in: float
    board_str: str
    arrive_str: str
    color: list


def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def fetch_feed(feed_id):
    """Fetch and parse GTFS realtime feed."""
    url = FEED_BASE_URL + feed_id
    response = requests.get(url, timeout=10)
    response.raise_for_status()

    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(response.content)
    return feed


def find_trips_for_route(feed, origin_stop, dest_stop):
    """Find all trips that serve both origin and destination stops."""
    trips = []

    for entity in feed.entity:
        if not entity.HasField("trip_update"):
            continue

        trip_update = entity.trip_update
        origin_time = None
        dest_time = None

        for stop_time in trip_update.stop_time_update:
            stop_id = stop_time.stop_id

            if stop_id == origin_stop:
                origin_time = stop_time.arrival.time

            elif stop_id == dest_stop:
                dest_time = stop_time.arrival.time

        if origin_time and dest_time and origin_time < dest_time:
            trips.append({
                "trip_id": trip_update.trip.trip_id,
                "route_id": trip_update.trip.route_id,
                "origin_time": origin_time,
                "dest_time": dest_time,
            })
    return trips


def format_time(unix_ts):
    """Format unix timestamp as HH:MM."""
    return datetime.fromtimestamp(unix_ts).strftime("%H:%M")


def setup_matrix(config):
    """Initialize the LED matrix."""
    options = RGBMatrixOptions()
    options.rows = config.get("led_rows", 32)
    options.cols = config.get("led_cols", 64)
    options.gpio_slowdown = config.get("led_gpio_slowdown", 2)
    options.brightness = config.get("led_brightness", 100)
    options.hardware_mapping = "regular"
    options.disable_hardware_pulsing = True
    if config.get("led_rotate"):
        options.pixel_mapper_config = f"Rotate:{config['led_rotate']}"

    matrix = RGBMatrix(options=options)
    font = graphics.Font()
    font_path = config.get("led_font", "./4x6.bdf")
    font.LoadFont(font_path)
    row_height = config.get("led_row_height", 7)

    return matrix, font, row_height


# Cache colors to avoid recreating them each frame
_color_cache = {}

def get_color(rgb):
    """Get or create a cached color."""
    key = tuple(rgb)
    if key not in _color_cache:
        _color_cache[key] = graphics.Color(rgb[0], rgb[1], rgb[2])
    return _color_cache[key]


def draw_routes(matrix, canvas, font, trips, best_name, row_height):
    """Draw route info on the LED matrix."""
    canvas.Clear()

    y = row_height  # First row baseline
    for trip in trips:
        is_best = (trip.route_name == best_name)

        color = get_color(trip.color)
        text = f"{trip.total_min:.0f} {trip.leave_in:.0f}"
        graphics.DrawText(canvas, font, 1, y, color, text)
        y += row_height

    return matrix.SwapOnVSync(canvas)

def main():
    config = load_config()
    poll_interval = config["poll_interval_seconds"]

    # Setup LED matrix if available
    matrix = None
    canvas = None
    font = None
    row_height = 7
    if HAS_MATRIX:
        matrix, font, row_height = setup_matrix(config)
        canvas = matrix.CreateFrameCanvas()
        print("LED matrix initialized")
    else:
        print("Running in CLI mode (no LED matrix)")

    feed_cache = {}

    while True:
        now = time.time()
        feed_cache.clear()

        print(f"\n=== {datetime.now().strftime('%H:%M:%S')} ===")

        all_trips = []

        for route in config["routes"]:
            feed_id = route["feed_id"]
            route_name = route["name"]

            if feed_id not in feed_cache:
                try:
                    feed_cache[feed_id] = fetch_feed(feed_id)
                except Exception as e:
                    print(f"{route_name}: Error - {e}")
                    continue

            feed = feed_cache[feed_id]
            feed_trips = find_trips_for_route(feed, route["origin_stop"], route["dest_stop"])

            walk_to_station = route["walk_to_station_min"] * 60
            earliest_board = now + walk_to_station
            catchable = [t for t in feed_trips if t["origin_time"] >= earliest_board]

            if not catchable:
                print(f"{route_name}: No trains")
                continue

            walk_to_office = route["walk_to_office_min"] * 60
            # TODO: the R is currently pink, oops.
            color = route.get("color", [255, 255, 255])

            for t in catchable:
                arrival_at_office = t["dest_time"] + walk_to_office
                all_trips.append(Trip(
                    route_name=route_name,
                    arrival_at_office=arrival_at_office,
                    total_min=(arrival_at_office - now) / 60,
                    leave_in=(t["origin_time"] - walk_to_station - now) / 60,
                    board_str=format_time(t["origin_time"]),
                    arrive_str=format_time(arrival_at_office),
                    color=color,
                ))

        # Sort by arrival time and filter by max arrival time
        all_trips.sort(key=lambda t: t.arrival_at_office)
        max_arrival_min = config.get("max_arrival_minutes", 60)
        all_trips = [t for t in all_trips if t.total_min <= max_arrival_min]

        for trip in all_trips:
            print(f"{trip.route_name}: Leave in {trip.leave_in:.0f}m, Board {trip.board_str} → Arrive {trip.arrive_str} ({trip.total_min:.0f} min)")

        best_option = all_trips[0].route_name if all_trips else None
        if best_option:
            print(f"\nBEST: {best_option}")

        # Update LED matrix (show top 9 - fits 64px height with 7px rows)
        if matrix and all_trips:
            canvas = draw_routes(matrix, canvas, font, all_trips[:9], best_option, row_height)

        time.sleep(poll_interval)


if __name__ == "__main__":
    main()
