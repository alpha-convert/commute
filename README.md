# MTA Commute Display

This project is entirely vibe-coded. Use at your own risk.

Find the fastest train to work and display it on an LED matrix.  Polls MTA GTFS
realtime feeds, compares multiple routes, and shows which train gets you to the
office soonest.

## Setup

```bash
pip install -r requirements.txt
```

## Usage

```bash
python mta.py
```

On a Raspberry Pi with an RGB LED matrix, it displays route times. Otherwise, it prints to the console.

## Configuration

Create a `config.json` file:

```json
{
  "poll_interval_seconds": 30,
  "led_brightness": 50,
  "led_rows": 32,
  "led_cols": 64,
  "led_gpio_slowdown": 2,
  "routes": [
    {
      "name": "2/3",
      "feed_id": "gtfs",
      "origin_stop": "234N",
      "dest_stop": "228N",
      "walk_to_station_min": 5,
      "walk_to_office_min": 10,
      "color": [255, 0, 0]
    }
  ]
}
```

### Config Schema

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `poll_interval_seconds` | int | yes | How often to fetch new train data |
| `led_brightness` | int | no | LED brightness 0-100 (default: 100) |
| `led_rows` | int | no | LED matrix rows (default: 32) |
| `led_cols` | int | no | LED matrix columns (default: 64) |
| `led_gpio_slowdown` | int | no | GPIO slowdown for Pi (default: 2) |
| `routes` | array | yes | List of route objects |

### Route Schema

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | yes | Display name (e.g., "2/3", "A/C") |
| `feed_id` | string | yes | MTA GTFS feed ID |
| `origin_stop` | string | yes | GTFS stop ID for your home station |
| `dest_stop` | string | yes | GTFS stop ID for your destination station |
| `walk_to_station_min` | int | yes | Minutes to walk from home to origin station |
| `walk_to_office_min` | int | yes | Minutes to walk from destination station to office |
| `color` | [r,g,b] | no | RGB color for LED display (default: white) |

### Finding Stop IDs

Stop IDs are found at https://openmobilitydata-data.s3-us-west-1.amazonaws.com/public/feeds/mta/79/20240103/original/stops.txt