#!/usr/bin/env python3
"""MTA Train Routing - Find the fastest train to work."""

import json
import time
from datetime import datetime
from pathlib import Path

import requests
from google.transit import gtfs_realtime_pb2

CONFIG_PATH = Path(__file__).parent / "config.json"
FEED_BASE_URL = "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2F"


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
                # Use departure time at origin (when we board)
                if stop_time.HasField("departure"):
                    origin_time = stop_time.departure.time
                elif stop_time.HasField("arrival"):
                    origin_time = stop_time.arrival.time

            elif stop_id == dest_stop:
                # Use arrival time at destination
                if stop_time.HasField("arrival"):
                    dest_time = stop_time.arrival.time
                elif stop_time.HasField("departure"):
                    dest_time = stop_time.departure.time

        # Only include trips that serve both stops
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


def main():
    config = load_config()
    poll_interval = config["poll_interval_seconds"]

    # Cache feeds to avoid duplicate requests for same feed_id
    feed_cache = {}

    while True:
        now = time.time()
        feed_cache.clear()

        print(f"\n=== {datetime.now().strftime('%H:%M:%S')} ===")

        best_option = None
        best_arrival = float("inf")

        for route in config["routes"]:
            feed_id = route["feed_id"]

            # Fetch feed (with caching)
            if feed_id not in feed_cache:
                try:
                    feed_cache[feed_id] = fetch_feed(feed_id)
                except Exception as e:
                    print(f"{route['name']}: Error fetching feed - {e}")
                    continue

            feed = feed_cache[feed_id]
            trips = find_trips_for_route(feed, route["origin_stop"], route["dest_stop"])

            # Filter to catchable trains
            walk_to_station = route["walk_to_station_min"] * 60
            earliest_board = now + walk_to_station

            catchable = [t for t in trips if t["origin_time"] >= earliest_board]

            if not catchable:
                print(f"{route['name']}: No upcoming trains")
                continue

            # Find best trip for this route
            walk_to_office = route["walk_to_office_min"] * 60

            for trip in sorted(catchable, key=lambda t: t["origin_time"]):
                arrival_at_office = trip["dest_time"] + walk_to_office
                total_time = (arrival_at_office - now) / 60

                board_str = format_time(trip["origin_time"])
                arrive_str = format_time(arrival_at_office)

                print(f"{route['name']}: Board {board_str} → Arrive {arrive_str} ({total_time:.0f} min)")

                if arrival_at_office < best_arrival:
                    best_arrival = arrival_at_office
                    best_option = route["name"]

                break  # Only show best option per route

        if best_option:
            total_min = (best_arrival - now) / 60
            print(f"\nBEST: {best_option} ({total_min:.0f} min)")

        time.sleep(poll_interval)


if __name__ == "__main__":
    main()
