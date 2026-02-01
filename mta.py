#!/usr/bin/env python3
"""MTA Train Routing - Find the fastest train to work."""

import json
import os
import time
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

# Short labels for display
ROUTE_LABELS = {
    "2/3 from Nevins → Park Pl": "2/3",
    "4/5 from Nevins → Fulton": "4/5",
    "A/C from Hoyt → Fulton": "A/C",
}


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
    options.hardware_mapping = "regular"
    options.disable_hardware_pulsing = True

    matrix = RGBMatrix(options=options)
    font = graphics.Font()
    font_path = "./6x10.bdf"
    font.LoadFont(font_path)

    return matrix, font


def draw_routes(matrix, canvas, font, results, best_name):
    """Draw route info on the LED matrix."""
    canvas.Clear()

    white = graphics.Color(255, 255, 255)

    y = 1  # First row baseline
    for name, total_min, leave_in, rgb in results:
        label = ROUTE_LABELS.get(name, name[:3])
        is_best = (name == best_name)

        color = graphics.Color(rgb[0], rgb[1], rgb[2]) if is_best else white
        star = "*" if is_best else ""
        text = f"{label} {total_min:.0f}m {leave_in:.0f}m{star}"

        graphics.DrawText(canvas, font, 1, y, color, text)
        y += 11  # Next row

    return matrix.SwapOnVSync(canvas)


def main():
    config = load_config()
    poll_interval = config["poll_interval_seconds"]

    # Setup LED matrix if available
    matrix = None
    canvas = None
    font = None
    if HAS_MATRIX:
        matrix, font = setup_matrix(config)
        canvas = matrix.CreateFrameCanvas()
        print("LED matrix initialized")
    else:
        print("Running in CLI mode (no LED matrix)")

    feed_cache = {}

    while True:
        now = time.time()
        feed_cache.clear()

        print(f"\n=== {datetime.now().strftime('%H:%M:%S')} ===")

        best_option = None
        best_arrival = float("inf")
        best_leave_in = None
        results = []  # (name, total_min, leave_in, color) for each route

        for route in config["routes"]:
            feed_id = route["feed_id"]

            if feed_id not in feed_cache:
                try:
                    feed_cache[feed_id] = fetch_feed(feed_id)
                except Exception as e:
                    print(f"{route['name']}: Error - {e}")
                    continue

            feed = feed_cache[feed_id]
            trips = find_trips_for_route(feed, route["origin_stop"], route["dest_stop"])

            walk_to_station = route["walk_to_station_min"] * 60
            earliest_board = now + walk_to_station
            catchable = [t for t in trips if t["origin_time"] >= earliest_board]

            if not catchable:
                print(f"{route['name']}: No trains")
                results.append((route["name"], 99, 99, route.get("color", [255, 255, 255])))
                continue

            walk_to_office = route["walk_to_office_min"] * 60
            first_trip = min(catchable, key=lambda t: t["origin_time"])

            arrival_at_office = first_trip["dest_time"] + walk_to_office
            total_time = (arrival_at_office - now) / 60

            leave_in = (first_trip["origin_time"] - walk_to_station - now) / 60

            board_str = format_time(first_trip["origin_time"])
            arrive_str = format_time(arrival_at_office)
            print(f"{route['name']}: Leave in {leave_in:.0f}m, Board {board_str} → Arrive {arrive_str} ({total_time:.0f} min)")

            results.append((route["name"], total_time, leave_in, route.get("color", [255, 255, 255])))

            if arrival_at_office < best_arrival:
                best_arrival = arrival_at_office
                best_option = route["name"]

        if best_option:
            total_min = (best_arrival - now) / 60
            print(f"\nBEST: {best_option} (Total time: {total_min:.0f} min)")

        # Update LED matrix
        if matrix and results:
            canvas = draw_routes(matrix, canvas, font, results, best_option)

        time.sleep(poll_interval)


if __name__ == "__main__":
    main()
