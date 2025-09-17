# import required libraries

# Configurable weather station ID
STATION_ID = 171455  # Change this to your station ID
STATION_URL = f"https://tempestwx.com/station/{STATION_ID}/"

from selenium import webdriver
from selenium.webdriver.chrome.options import Options

import re
import time
import tempfile
import os
from selenium.webdriver.chrome.service import Service

def get_websocket_url_and_api_key_selenium(station_url):
	"""
	Use Selenium to load the page and extract the WebSocket URL and API key from network activity or page scripts.
	"""
	chrome_options = Options()
	chrome_options.add_argument('--headless')
	chrome_options.add_argument('--no-sandbox')
	chrome_options.add_argument('--disable-dev-shm-usage')
	chrome_options.add_argument('--disable-gpu')
	chrome_options.add_argument('--window-size=1920,1080')
	chrome_options.add_argument('--remote-debugging-port=9222')
	chrome_options.add_argument('--single-process')
	chrome_options.binary_location = '/usr/bin/chromium-browser'

	# Use a unique temporary user data directory in /tmp for WSL compatibility
	with tempfile.TemporaryDirectory(dir="/tmp") as user_data_dir:
		chrome_options.add_argument(f'--user-data-dir={user_data_dir}')

		# Explicitly set the ChromeDriver path
		chromedriver_path = '/usr/bin/chromedriver'
		service = Service(executable_path=chromedriver_path)
		driver = webdriver.Chrome(service=service, options=chrome_options)
		driver.get(station_url)
		time.sleep(5)  # Wait for JS to load

		# Try to find WebSocket URL and API key in page source or scripts
		ws_url = None
		api_key = None
		page_source = driver.page_source
		scripts = driver.find_elements('tag name', 'script')
		for script in scripts:
			script_content = script.get_attribute('innerHTML')
			if script_content:
				ws_match = re.search(r'wss://[\w\.-/:?&=]+', script_content)
				key_match = re.search(r'api_key["\']?\s*[:=]\s*["\']([\w-]+)["\']', script_content)
				if ws_match:
					ws_url = ws_match.group(0)
				if key_match:
					api_key = key_match.group(1)
				if ws_url and api_key:
					break

		driver.quit()
		return ws_url, api_key


if __name__ == "__main__":
	ws_url, api_key = get_websocket_url_and_api_key_selenium(STATION_URL)
	print(f"WebSocket URL: {ws_url}")
	print(f"API Key: {api_key}")
