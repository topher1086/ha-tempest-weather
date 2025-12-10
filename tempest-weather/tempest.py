from __future__ import annotations  # noqa: D100, INP001

import json
import random
import sys
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path

import paho.mqtt.client as mqtt
import pytz
import yaml
from loguru import logger
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By

in_addon = not __file__.startswith("/workspaces/") and not __file__.startswith(
    "/home/chris/",
)

settings = {}
try:
    with Path("./data/options.json").open() as json_file:
        settings = json.load(json_file)
except FileNotFoundError:
    with Path("./tempest-weather/config.yaml").open() as yaml_file:
        full_config = yaml.safe_load(yaml_file)

    settings = full_config["options"]

try:
    with Path("./tempest-weather/test_config.yaml").open() as yaml_file:
        test_config = yaml.safe_load(yaml_file)
        settings.update(test_config)
except FileNotFoundError:
    test_config = {}

# reset the logging level from DEBUG by default
logger.remove()
logger.add(sys.stderr, level=settings["LOGGING_LEVEL"] if in_addon else "DEBUG")

logger.info("Running in add-on" if in_addon else "Running outside of add-on")

STATION_ID = settings.get("WEATHER_STATION_ID")


# MQTT config (add these to your config.yaml or test_config.yaml as needed)
MQTT_HOST = settings.get("MQTT_HOST")
MQTT_PORT = settings.get("MQTT_PORT", 1884)
MQTT_TRANSPORT = settings.get("MQTT_TRANSPORT", "websockets")
MQTT_USER = settings.get("MQTT_USER")
MQTT_PASS = settings.get("MQTT_PASS")
MQTT_CLIENT_ID = f"tempest_{STATION_ID}"
MQTT_BASE = "homeassistant"

FORECAST_HOURS = 12
NIGHT_LUX_LEVEL = 10
NIGHT_HOUR_START = 19
DAY_HOUR_START = 6

# Get the path of the current working directory
# import os

# current_path = os.getcwd()
# print(f"Listing for: {current_path}\n")

# # os.listdir() returns a list of strings (filenames)
# try:
#     for item in os.listdir():
#         print(item)
# except FileNotFoundError:
#     print(f"Error: The directory '{current_path}' was not found.")

# dirs_to_list = ["./chromedriver-linux64", "./chrome-headless-shell-linux64"]
# for directory in dirs_to_list:
#     print(f"Listing for: {os.path.abspath(directory)}\n")
#     try:
#         print("\n".join(os.listdir(directory)))
#     except FileNotFoundError:
#         print(f"Error: The directory '{directory}' was not found.")
#     print("-" * 20)

if in_addon:
    chromedriver_path = "/usr/bin/chromedriver"
    chrome_shell_binary_location = "/usr/bin/chromium"
else:
    chromedriver_path = "./chromedriver-linux64/chromedriver"
    chrome_shell_binary_location = "./chrome-headless-shell-linux64/chrome-headless-shell"


# --- MQTT Publisher Class ---
class MQTTPublisher:
    """Publishes weather sensor data to an MQTT broker, maintaining a persistent connection and only publishing changed values.

    Attributes:
        host (str): MQTT broker host.
        port (int): MQTT broker port.
        user (str | None): MQTT username.
        password (str | None): MQTT password.
        client_id (str): MQTT client ID.
        base (str): MQTT topic base.
        station_id (str): Weather station ID.
        client (mqtt.Client | None): The MQTT client instance.
        last_values (dict): Last published values for each sensor.
        sensor_meta (dict): Metadata for each sensor (unit, device_class, icon).

    """

    def __init__(
        self,
    ) -> None:
        """Initialize the MQTTPublisher with connection and sensor info."""
        self.host = MQTT_HOST
        self.port = MQTT_PORT
        self.transport = MQTT_TRANSPORT
        self.user = MQTT_USER
        self.password = MQTT_PASS
        self.client_id = MQTT_CLIENT_ID
        self.base = MQTT_BASE
        self.station_id = STATION_ID
        self.client: mqtt.Client | None = None
        self.last_values: dict[str, str | None] = {}
        self.sensors_configured: set[str] = set()
        self.update_count: int = 0
        self.sensor_meta: dict[str, dict[str, str]] = {
            "temperature": {"unit": "°F", "device_class": "temperature"},
            "humidity": {"unit": "%", "device_class": "humidity"},
            "feels_like": {"unit": "°F", "device_class": "temperature"},
            "dew_point": {"unit": "°F", "device_class": "temperature"},
            "pressure": {"unit": "inHg", "device_class": "pressure"},
            "wind_speed": {"unit": "mph", "device_class": "wind_speed", "icon": "mdi:weather-windy", "suggested_display_precision": 0},
            "wind_gust_low": {"unit": "mph", "device_class": "wind_speed", "icon": "mdi:weather-windy", "suggested_display_precision": 0},
            "wind_gust_high": {"unit": "mph", "device_class": "wind_speed", "icon": "mdi:weather-windy", "suggested_display_precision": 0},
            "wind_direction": {"unit": "°", "icon": "mdi:compass"},
            "wind_direction_cardinal": {"icon": "mdi:compass-outline"},
            "wind_bearing": {"unit": "°", "icon": "mdi:compass"},
            "uv": {"unit": "UV", "icon": "mdi:weather-sunny-alert"},
            "brightness": {"unit": "lx", "device_class": "illuminance", "icon": "mdi:brightness-7"},
            "precipitation_rate": {"icon": "mdi:weather-rainy"},
            "precipitation_today": {"unit": "in", "device_class": "precipitation", "icon": "mdi:weather-rainy", "suggested_display_precision": 2},
            "precipitation_yesterday": {"unit": "in", "device_class": "precipitation", "icon": "mdi:weather-rainy", "suggested_display_precision": 2},
            "lightning_last_3_hrs": {"unit": "strikes", "icon": "mdi:flash"},
            "last_lightning_strike": {"icon": "mdi:flash-alert"},
            "lightning_last_distance": {"unit": "mi", "icon": "mdi:map-marker-distance"},
            "daily_precip_chance": {"unit": "%", "icon": "mdi:weather-partly-rainy"},
            "daily_temp_high": {"unit": "°F", "device_class": "temperature", "icon": "mdi:thermometer-high"},
            "daily_temp_low": {"unit": "°F", "device_class": "temperature", "icon": "mdi:thermometer-low"},
            "forecast_day_desc": {"icon": "mdi:weather-partly-cloudy"},
            "current_conditions": {"icon": "mdi:weather-partly-cloudy"},
            "forecast": {"icon": "mdi:weather-partly-cloudy", "value_template": "{{ value_json[0].condition }}"},
        }

        self._setup_client()

    def _setup_client(self) -> None:
        """Set up and connect the MQTT client."""
        if not mqtt:
            logger.warning("paho-mqtt not installed, MQTT publishing disabled.")
            return
        self.client = mqtt.Client(callback_api_version=2, client_id=self.client_id, transport=self.transport)
        if self.user:
            self.client.username_pw_set(self.user, self.password)
        try:
            self.client.connect(self.host, self.port, 60)
            self.client.loop_start()
            logger.info(f"Connected to MQTT broker at {self.host}:{self.port}")
        except Exception as e:
            logger.warning(f"Could not connect to MQTT broker: {e}")
            self.client = None

    def publish_sensor(self, sensor: str, value: str | None, force: bool = False) -> None:  # noqa: FBT001, FBT002
        """Publish a single sensor value to MQTT if it has changed since the last publish.

        Args:
            sensor (str): The sensor name.
            value (str | None): The sensor value.
            force (bool): Whether to force publish the value.

        """
        if not self.client:
            return
        # Only publish if value changed
        if self.last_values.get(sensor) == value and not force:
            return
        self.last_values[sensor] = value
        object_id = f"tempest_{sensor}"
        unique_id = f"tempest_{sensor}_{self.station_id}"
        config_topic = f"{self.base}/sensor/{object_id}/config"
        state_topic = f"{self.base}/sensor/{object_id}/state"

        if sensor not in self.sensors_configured:
            meta = self.sensor_meta.get(sensor, {})
            config_payload = {
                "name": f"{sensor.replace('_', ' ').title()}",
                "state_topic": state_topic,
                "unique_id": unique_id,
                "device": {
                    "identifiers": [f"tempest_{self.station_id}"],
                    "manufacturer": "WeatherFlow",
                    "model": "Tempest",
                    "name": f"Tempest Station {self.station_id}",
                },
            }
            if meta.get("unit"):
                config_payload["unit_of_measurement"] = meta["unit"]
            if meta.get("device_class"):
                config_payload["device_class"] = meta["device_class"]
            if meta.get("icon"):
                config_payload["icon"] = meta["icon"]
            if meta.get("suggested_display_precision"):
                config_payload["suggested_display_precision"] = meta["suggested_display_precision"]
            if meta.get("value_template"):
                config_payload["value_template"] = meta["value_template"]
                config_payload["json_attributes_topic"] = state_topic
                if sensor == "forecast":
                    config_payload["json_attributes_template"] = "{{ {'forecast': value_json} | tojson }}"

            self.client.publish(config_topic, json.dumps(config_payload), retain=True)

            self.sensors_configured.add(sensor)
            logger.info(f"Published MQTT config for {sensor}")

        # self.client.publish(state_topic, str(value) if value is not None else "", retain=True)
        val = json.dumps(value) if isinstance(value, list | dict) else str(value) if value is not None else ""

        self.client.publish(state_topic, val, retain=True)

    def publish_weather(self, weather_data: dict[str, str | None]) -> None:
        """Publish all weather data to MQTT, only sending values that have changed.

        Args:
            weather_data (dict): Dictionary of sensor names to values.

        """
        if not self.client:
            logger.warning("MQTT client not connected, reconnecting.")
            self._setup_client()
            return

        self.update_count += 1
        force = self.update_count % 60 == 0
        if force:
            logger.info("Forcing MQTT publish for all sensors.")
        for k, v in weather_data.items():
            logger.info(f"{k.capitalize()}: {v}")
            self.publish_sensor(k, v, force=force)

    def disconnect(self) -> None:
        """Disconnect from the MQTT broker and stop the client loop."""
        if self.client:
            self.client.loop_stop()
            self.client.disconnect()
            logger.info("Disconnected from MQTT broker.")


def _clean_degrees(val: str) -> str:
    """Remove degree symbols and whitespace."""
    return val.replace("°F", "").replace("°", "").strip()


def _clean_percent(val: str) -> str:
    """Remove percent symbols and whitespace."""
    return val.replace("%", "").strip()


def _clean_inches(val: str) -> str:
    """Remove inch marks and whitespace."""
    return val.replace('"', "").strip()


def _clean_precip_rate(val: str) -> str:
    """Clean precipitation rate."""
    return "Dry" if val.lower() == "none" else val.title()


def _clean_wind_direction(val: str) -> str:
    """Extract cardinal wind direction."""
    return val.split(" ")[-1].upper()


def _clean_brightness(val: str) -> str:
    """Clean brightness value."""
    return val.replace(" lux", "").strip()


def _to_iso_datetime(time_str: str, weather_data: dict) -> str:
    """Convert 'X am/pm' time to ISO 8601 format for today or tomorrow."""
    tz = pytz.timezone(weather_data["station_timezone"]) if weather_data.get("station_timezone") else pytz.timezone("America/Los_Angeles")

    now = datetime.now(tz)
    # Special case for "Now"
    if time_str.lower() == "now":
        return now.isoformat()

    # Parse time like "2 pm"
    try:
        hour_time = datetime.strptime(time_str, "%I %p")
        # Create a datetime object for today with the parsed time
        forecast_dt = now.replace(hour=hour_time.hour, minute=0, second=0, microsecond=0)

        # If the forecast time is in the past, it must be for tomorrow
        if forecast_dt < now:
            forecast_dt += timedelta(days=1)

        return forecast_dt.isoformat()
    except ValueError:
        logger.warning(f"Could not parse time: {time_str}")
        return time_str  # Return original if parsing fails


def _parse_wind_gusts(val: str, weather_data: dict) -> None:
    """Parse wind gust data into low and high values."""
    n_val = val.replace(" mph", "").strip().replace(" ", "")
    splits = n_val.split("-")
    low_val = splits[0]
    high_val = splits[1] if len(splits) > 1 else splits[0]
    weather_data["wind_gust_low"] = low_val
    weather_data["wind_gust_high"] = high_val


def _parse_lightning_distance(val: str) -> int:
    """Parse lightning distance, averaging if a range is given."""
    new_val = str(val).replace(" mi", "").strip().replace(" ", "")
    splits = new_val.split("-")
    spl_cnt = len(splits)
    total_dist = sum(float(s) for s in splits) if spl_cnt > 0 else 0.0
    return int(total_dist / spl_cnt) if spl_cnt > 0 else 0


def _clean_condition(val: str) -> str:
    """Clean condition string."""
    cond_list = [
        "clear-night",
        "cloudy",
        "fog",
        "hail",
        "lightning",
        "lightning-rainy",
        "partlycloudy",
        "pouring",
        "rainy",
        "snowy",
        "snowy-rainy",
        "sunny",
        "windy",
        "windy-variant",
        "exceptional",
    ]

    if not isinstance(val, str):
        return val

    val_clean = val.strip().lower()

    # Mapping for special cases
    special_cases = {
        "thunderstorm": "lightning-rainy",
        "partlycloudy": "partlycloudy",
        "sunny": "sunny",
        "clear-night": "clear-night",
        "clear": "sunny",
    }

    # Check for direct match
    if val_clean in cond_list:
        return val_clean

    if val_clean in special_cases:
        return special_cases[val_clean]

    # Check for special cases
    if "thunderstorm" in val_clean:
        return special_cases["thunderstorm"]
    if "partly" in val_clean and "cloudy" in val_clean:
        return special_cases["partlycloudy"]
    if "clear" in val_clean and "night" in val_clean:
        return special_cases["clear-night"]
    if "clear" in val_clean and "day" in val_clean:
        return special_cases["sunny"]

    # Check if any condition in cond_list is a substring
    found_cond = next((c for c in cond_list if c in val_clean), None)
    return found_cond if found_cond else val_clean


def wind_cardinal_to_degrees(cardinal: str) -> float:
    """Convert wind cardinal direction to degrees.

    Args:
        cardinal (str): Wind direction as a cardinal string (e.g., 'N', 'ESE', 'SW').

    Returns:
        float: Degrees corresponding to the cardinal direction (0-360).

    """
    cardinal = cardinal.upper().strip()
    directions = [
        "N",
        "NNE",
        "NE",
        "ENE",
        "E",
        "ESE",
        "SE",
        "SSE",
        "S",
        "SSW",
        "SW",
        "WSW",
        "W",
        "WNW",
        "NW",
        "NNW",
    ]
    if cardinal in directions:
        return directions.index(cardinal) * 22.5
    return 0.0  # Default to North if unknown


def main() -> None:  # noqa: C901, PLR0915
    """Scrapes weather data from a Tempest Weather station web page using Selenium and headless Chrome."""

    def safe_text(selector: str) -> str | None:
        try:
            return driver.find_element(By.CSS_SELECTOR, selector).text
        except Exception:
            return None

    def get_aria_label_nested(selector: str) -> str | None:
        elements = driver.find_elements(By.CSS_SELECTOR, selector)

        return get_aria_nested(elements)

    def get_aria_nested(element_list: list) -> str | None:
        for element in element_list:
            try:
                a_label = element.accessible_name
                if isinstance(a_label, str) and len(a_label) > 0:
                    return a_label
            except AttributeError:  # noqa: PERF203
                a_label = None

        for element in element_list:
            children = element.find_elements(By.XPATH, "./*")
            a_label = get_aria_nested(children)
            if a_label:
                return a_label
        return None

    # time.sleep(600)

    url = f"https://tempestwx.com/station/{STATION_ID}"
    service = ChromeService(chromedriver_path)
    chrome_options = webdriver.ChromeOptions()

    # Set the binary location (your code already does this correctly)
    chrome_options.binary_location = chrome_shell_binary_location

    # --- ADD THESE ARGUMENTS ---
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")  # Essential for running as root in Docker
    chrome_options.add_argument("--disable-dev-shm-usage")  # Overcomes limited resource problems
    chrome_options.add_argument("--disable-gpu")  # Applicable for headless environments
    chrome_options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    )
    # ---------------------------

    driver = webdriver.Chrome(
        service=service,
        options=chrome_options,
    )
    driver.get(url)

    css_refs = {
        "station_timezone": "#station-timezone",
        "temperature": "[data-param='param-air_temp_with_symbol_and_units']",
        "dew_point": "[data-param='param-heat_index_or_dew_point_display']",
        "humidity": "[data-param='param-rh_with_symbol']",
        "feels_like": "#cc-feels-like-temp",
        "pressure": "[data-param='param-sea_level_pres_display']",
        "pressure_trend": "[data-param='param-pres_trend_localized']",
        "lightning_last_strike": "[data-param='param-lightning_last_strike_fuzzy']",
        "lightning_last_3_hrs": "[data-param='param-lightning_strike_count_last_3hrs']",
        "lightning_last_distance": "[data-param='param-lightning_last_strike_distance_text_display']",
        "wind_direction_cardinal": "[data-param='param-wind_dir_display']",
        "wind_gusts": "[data-param='param-wind_lull_gust_with_units']",
        "wind_speed": "[data-param='param-wind_avg_display']",
        "precipitation_rate": "[data-param='param-precip_rate_text_display_localized']",
        "precipitation_today": "[data-param='param-precip_accum_local_today_final_display_with_units']",
        "precipitation_yesterday": "[data-param='param-precip_accumm_local_yesterday_final_display_with_units']",
        "uv": "[data-param='param-uv_with_index']",
        "brightness": "[data-param='param-lux_display_with_units']",
        "daily_precip_chance": "p.daily-precip-chance",  # CSS selector for daily precip chance
        "daily_temp_high": "p.daily-temp-high",  # CSS selector for daily high
        "daily_temp_low": "p.daily-temp-low",  # CSS selector for daily low
        "forecast_day_desc": "p.forecast-day-desc",  # CSS selector for forecast day description
        "current_conditions": "#conditions-str",
    }

    css_refs.update({f"forecast_hourly_condition_{x}": f"tr.hourly-sky :nth-child({x})" for x in range(1, FORECAST_HOURS + 1)})

    css_refs.update({f"forecast_hourly_time_{x}": f"tr.hour :nth-child({x})" for x in range(1, FORECAST_HOURS + 1)})

    css_refs.update({f"forecast_hourly_temp_{x}": f"tr.hourly-temp :nth-child({x})" for x in range(1, FORECAST_HOURS + 1)})

    css_refs.update({f"forecast_hourly_precip_{x}": f"tr.hourly-precip :nth-child({x})" for x in range(1, FORECAST_HOURS + 1)})

    css_refs.update({f"forecast_hourly_wind_{x}": f"tr.hourly-wind :nth-child({x})" for x in range(1, FORECAST_HOURS + 1)})

    css_refs.update({f"forecast_hourly_wind_direction_{x}": f"tr.hourly-wind :nth-child({x})" for x in range(1, FORECAST_HOURS + 1)})

    weather_data = dict.fromkeys(css_refs.keys())

    cleaning_rules = {
        "temperature": _clean_degrees,
        "dew_point": _clean_degrees,
        "daily_temp_high": _clean_degrees,
        "daily_temp_low": _clean_degrees,
        "feels_like": _clean_degrees,
        "forecast_hourly_temp_": _clean_degrees,
        "forecast_hourly_precip_": _clean_percent,
        "humidity": _clean_percent,
        "daily_precip_chance": _clean_percent,
        "precipitation_today": _clean_inches,
        "precipitation_yesterday": _clean_inches,
        "precipitation_rate": _clean_precip_rate,
        "pressure_trend": _clean_precip_rate,
        "forecast_hourly_wind_direction_": _clean_wind_direction,
        "wind_gusts": lambda val, data=weather_data: _parse_wind_gusts(val, data),
        "lightning_last_distance": _parse_lightning_distance,
        "brightness": _clean_brightness,
        "current_conditions": _clean_condition,
        "forecast_hourly_condition_": _clean_condition,
        "forecast_hourly_time_": lambda val, data=weather_data: _to_iso_datetime(val, data),
    }

    sleep_time = 15
    loops = 3600 / sleep_time

    # Initialize persistent MQTT publisher
    mqtt_publisher = MQTTPublisher()

    try:
        for _ in range(int(loops)):
            try:
                time.sleep(sleep_time)

                for k, v in css_refs.items():
                    new_val = (
                        get_aria_label_nested(v)
                        if k.startswith(("forecast_hourly_wind_direction_", "forecast_hourly_condition_"))
                        else driver.find_element(By.CSS_SELECTOR, v).get_attribute("aria-label")
                        if k == "weather"
                        else safe_text(v)
                    )

                    if new_val:
                        # Find and apply the correct cleaning rule
                        rule_key = next((rule for rule in cleaning_rules if k.startswith(rule)), None)
                        if rule_key:
                            if rule_key in ["wind_gusts"]:
                                cleaning_rules[rule_key](new_val)
                                continue
                            new_val = cleaning_rules[rule_key](new_val)

                        weather_data[k] = new_val

                if weather_data.get("wind_direction_cardinal"):
                    # Convert cardinal direction to degrees
                    weather_data["wind_bearing"] = wind_cardinal_to_degrees(weather_data["wind_direction_cardinal"])

                forecast = []
                for i in range(1, FORECAST_HOURS + 1):
                    temp_val = weather_data.get(f"forecast_hourly_temp_{i}")
                    precip_val = weather_data.get(f"forecast_hourly_precip_{i}")
                    wind_val = weather_data.get(f"forecast_hourly_wind_{i}")

                    forecast.append(
                        {
                            "condition": weather_data.get(f"forecast_hourly_condition_{i}"),
                            "datetime": weather_data.get(f"forecast_hourly_time_{i}"),
                            "native_temperature": float(temp_val) if temp_val is not None else None,
                            "precipitation_probability": int(precip_val) if precip_val is not None else None,
                            "native_wind_speed": int(wind_val) if wind_val is not None else None,
                            "wind_bearing": wind_cardinal_to_degrees(weather_data.get(f"forecast_hourly_wind_direction_{i}")),
                        }
                    )
                weather_data["forecast"] = forecast

                # Click the 'Observations' button if present after each loop
                try:
                    view_btn = driver.find_element(By.ID, "view-btn")
                    view_btn.click()
                    logger.debug("Clicked the 'Observations' button.")
                except Exception as e:
                    logger.warning(f"Could not click 'Observations' button: {e}")

                mqtt_publisher.publish_weather(weather_data)

                logger.info("*" * 40)

                # add an extra random sleep here to avoid looking like a script
                time.sleep(random.randint(1, sleep_time))  # noqa: S311

            except Exception as e:
                logger.error(f"Error occurred: {e}")
                logger.error(traceback.format_exc())
    finally:
        driver.quit()
        mqtt_publisher.disconnect()


if __name__ == "__main__":
    while True:
        main()
