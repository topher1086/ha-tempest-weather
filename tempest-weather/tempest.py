from __future__ import annotations  # noqa: D100

import json
import sys
import time
from pathlib import Path

import paho.mqtt.client as mqtt
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
    test_config = {}

# reset the logging level from DEBUG by default
logger.remove()
logger.add(sys.stderr, level=settings["LOGGING_LEVEL"] if in_addon else "DEBUG")

STATION_ID = settings.get("WEATHER_STATION_ID")


# MQTT config (add these to your config.yaml or test_config.yaml as needed)
MQTT_HOST = "supervisor" if in_addon else settings.get("MQTT_HOST")
MQTT_PORT = settings.get("MQTT_PORT", 1883)
MQTT_USER = settings.get("MQTT_USER")
MQTT_PASS = settings.get("MQTT_PASS")
MQTT_CLIENT_ID = f"tempest_{STATION_ID}"
MQTT_BASE = "homeassistant"


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

    def __init__(  # noqa: PLR0913
        self,
        host: str,
        port: int,
        user: str | None,
        password: str | None,
        client_id: str,
        base: str,
        station_id: str,
    ) -> None:
        """Initialize the MQTTPublisher with connection and sensor info."""
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.client_id = client_id
        self.base = base
        self.station_id = station_id
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
            "wind_speed": {"unit": "mph", "device_class": "wind_speed", "icon": "mdi:weather-windy"},
            "wind_gust_low": {"unit": "mph", "device_class": "wind_speed", "icon": "mdi:weather-windy"},
            "wind_gust_high": {"unit": "mph", "device_class": "wind_speed", "icon": "mdi:weather-windy"},
            "wind_direction": {"unit": "°", "icon": "mdi:compass"},
            "wind_direction_cardinal": {"icon": "mdi:compass-outline"},
            "uv": {"device_class": "uv_index", "icon": "mdi:weather-sunny-alert"},
            "precipitation": {"unit": "in", "device_class": "precipitation", "icon": "mdi:weather-rainy"},
            "precipitation_today": {"unit": "in", "device_class": "precipitation", "icon": "mdi:weather-rainy", "suggested_display_precision": 2},
            "precipitation_yesterday": {"unit": "in", "device_class": "precipitation", "icon": "mdi:weather-rainy", "suggested_display_precision": 2},
            "lightning_last_3_hrs": {"icon": "mdi:flash"},
            "last_lightning_strike": {"icon": "mdi:flash-alert"},
            "lightning_last_distance": {"icon": "mdi:map-marker-distance"},
            "daily_precip_chance": {"unit": "%", "icon": "mdi:weather-partly-rainy"},
            "daily_temp_high": {"unit": "°F", "device_class": "temperature", "icon": "mdi:thermometer-high"},
            "daily_temp_low": {"unit": "°F", "device_class": "temperature", "icon": "mdi:thermometer-low"},
        }
        self._setup_client()

    def _setup_client(self) -> None:
        """Set up and connect the MQTT client."""
        if not mqtt:
            logger.warning("paho-mqtt not installed, MQTT publishing disabled.")
            return
        self.client = mqtt.Client(callback_api_version=2, client_id=self.client_id)
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
            self.client.publish(config_topic, json.dumps(config_payload), retain=True)

            self.sensors_configured.add(sensor)
            logger.info(f"Published MQTT config for {sensor}")

        self.client.publish(state_topic, str(value) if value is not None else "", retain=True)

    def publish_weather(self, weather_data: dict[str, str | None]) -> None:
        """Publish all weather data to MQTT, only sending values that have changed.

        Args:
            weather_data (dict): Dictionary of sensor names to values.

        """
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


def main() -> None:  # noqa: C901, PLR0915
    """Scrapes weather data from a Tempest Weather station web page using Selenium and headless Chrome."""

    def safe_text(selector: str) -> str | None:
        try:
            return driver.find_element(By.CSS_SELECTOR, selector).text
        except Exception:
            return None

    url = f"https://tempestwx.com/station/{STATION_ID}/grid"
    service = ChromeService("./chromedriver-linux64/chromedriver")
    chrome_options = webdriver.ChromeOptions()
    chrome_options.binary_location = "./chrome-headless-shell-linux64/chrome-headless-shell"
    chrome_options.add_argument("--headless")
    chrome_options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    )
    driver = webdriver.Chrome(
        service=service,
        options=chrome_options,
    )

    driver.get(url)

    css_refs = {
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
        "daily_precip_chance": "p.daily-precip-chance",  # CSS selector for daily precip chance
        "daily_temp_high": "p.daily-temp-high",  # CSS selector for daily high
        "daily_temp_low": "p.daily-temp-low",  # CSS selector for daily low
    }

    weather_data = dict.fromkeys(css_refs.keys())

    sleep_time = 15
    loops = 3600 / sleep_time

    # Initialize persistent MQTT publisher
    mqtt_publisher = MQTTPublisher(
        MQTT_HOST,
        MQTT_PORT,
        MQTT_USER,
        MQTT_PASS,
        MQTT_CLIENT_ID,
        MQTT_BASE,
        STATION_ID,
    )

    try:
        for _ in range(int(loops)):
            try:
                time.sleep(sleep_time)  # Wait for JS to render data; adjust as needed

                for k, v in css_refs.items():
                    new_val = safe_text(v)
                    if new_val:
                        if k in ["temperature", "dew_point", "daily_temp_high", "daily_temp_low"]:
                            new_val = new_val.replace("°F", "").replace("°", "").strip()
                        if k == "feels_like":
                            new_val = new_val.replace("°", "").strip()

                        if k in {"humidity", "daily_precip_chance"}:
                            new_val = new_val.replace("%", "").strip()

                        if k in ["precipitation_today", "precipitation_yesterday"]:
                            new_val = new_val.replace('"', "").strip()

                        if k == "wind_gusts":
                            n_val = new_val.replace(" mph", "").strip().replace(" ", "")
                            splits = n_val.split("-")
                            low_val = splits[0]
                            high_val = splits[1] if len(splits) > 1 else splits[0]

                            weather_data["wind_gust_low"] = low_val
                            weather_data["wind_gust_high"] = high_val
                            continue

                        weather_data[k] = new_val

                # Click the 'Observations' button if present after each loop
                try:
                    view_btn = driver.find_element(By.ID, "view-btn")
                    view_btn.click()
                    logger.debug("Clicked the 'Observations' button.")
                except Exception as e:
                    logger.warning(f"Could not click 'Observations' button: {e}")

                mqtt_publisher.publish_weather(weather_data)

                logger.info("*" * 20)

            except Exception as e:
                logger.error(f"Error occurred: {e}")
    finally:
        driver.quit()
        mqtt_publisher.disconnect()
if __name__ == "__main__":
    while True:
        main()
