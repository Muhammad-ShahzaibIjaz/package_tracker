# Standard library imports
import datetime
import json
import os
import re
import time
import typing
import threading
import random

# Third-party imports
import cachetools
import flask
import playwright.sync_api
import python_socks.sync
import requests
import requests.adapters
import requests.utils

from shipment_variables import country_cache, courier_cache, status_cache

try:
    import requests.packages.urllib3 as urllib3
except ImportError:
    import urllib3

HTTPConnection = urllib3.connection.HTTPConnection
HTTPSConnection = urllib3.connection.HTTPSConnection
HTTPConnectionPool = urllib3.connectionpool.HTTPConnectionPool
HTTPSConnectionPool = urllib3.connectionpool.HTTPSConnectionPool
PoolManager = urllib3.PoolManager
real_get_connection = requests.adapters.HTTPAdapter.get_connection

def patch_proxy_connection():
    """Patch proxy connection to chain"""
    requests.adapters.HTTPAdapter.get_connection = patched_get_connection

def proxy_from_url(url: str):
    """Parse proxy URL"""
    for scheme in "socks4", "socks5":
        scheme_rdns = scheme + "h"
        if url.startswith(scheme_rdns):
            url = url.replace(scheme_rdns, scheme, 1)
            return python_socks.sync.Proxy.from_url(url, rdns=True)
    return python_socks.sync.Proxy.from_url(url)

def parse_proxychain_url(url):
    """Parse proxychain URL"""
    proxy = map(str.strip, url.split(","))
    proxy = filter(None, proxy)
    proxy = list(map(proxy_from_url, proxy))
    return python_socks.sync.ProxyChain(proxy)

class ChainConnection(HTTPConnection):
    def __init__(self, *args, **kwargs):
        self._socks_options = kwargs.pop("_socks_options")
        super().__init__(*args, **kwargs)

    def _new_conn(self):
        proxy = self._socks_options["proxychain"]
        conn = proxy.connect(self.host, self.port)
        conn.setblocking(True)
        return conn

class ChainHTTPSConnection(ChainConnection, HTTPSConnection):
    pass

class ChainHTTPConnectionPool(HTTPConnectionPool):
    ConnectionCls = ChainConnection

class ChainHTTPSConnectionPool(HTTPSConnectionPool):
    ConnectionCls = ChainHTTPSConnection

class ProxyChainManager(PoolManager):
    pool_classes_by_scheme = {
        "http": ChainHTTPConnectionPool,
        "https": ChainHTTPSConnectionPool,
    }
    def __init__(self, proxy_url, num_pools, **connection_pool_kw):
        proxy = parse_proxychain_url(proxy_url)
        connection_pool_kw["_socks_options"] = dict(proxychain=proxy)
        super().__init__(num_pools, None, **connection_pool_kw)
        self.pool_classes_by_scheme = __class__.pool_classes_by_scheme

def patched_get_connection(self, url, proxies):
    """Get a connection based on the proxy scheme"""
    proxy = requests.utils.select_proxy(url, proxies)
    is_proxychain = proxy and "," in proxy
    if not is_proxychain:
        return real_get_connection(self, url, proxies)

    manager = self.proxy_manager.get(proxy)
    if manager is None:
        manager = ProxyChainManager(
            proxy,
            num_pools=self._pool_connections,
            maxsize=self._pool_maxsize,
            block=self._pool_block,
        )
        self.proxy_manager[proxy] = manager

    return manager.connection_from_url(url)

CACHE_JSON = "cache.json"
CACHE_CACHE = cachetools.TTLCache(maxsize=1, ttl=10)

class JsonFileHandler:
    def __init__(self, file_path: str, cache: cachetools.TTLCache, default_data: typing.Dict):
        self.file_path = file_path
        self.cache = cache
        self.default_data = default_data

    def read(self) -> typing.Dict:
        if self.file_path in self.cache:
            return self.cache[self.file_path]
        
        try:
            if os.path.exists(self.file_path) and os.path.getsize(self.file_path) > 0:
                with open(self.file_path, 'r') as file:
                    data = json.load(file)
                    self.cache[self.file_path] = data
                    return data
            else:
                self.initialize()
                return self.read()
        except FileNotFoundError:
            print(f"[!] {self.file_path} not found, initializing with default data.")
            self.initialize()
            return self.read()

    def write(self, data: typing.Dict) -> None:
        temp_file = f"{self.file_path}.tmp"
        with open(temp_file, 'w') as file:
            try:
                json.dump(data, file, indent=4)
            except (TypeError, ValueError) as e:
                print(f"[!] Invalid JSON data for {self.file_path}: {e}")
                return    
        os.replace(temp_file, self.file_path)
        self.cache[self.file_path] = data

    def initialize(self) -> None:
        if not (os.path.exists(self.file_path) and os.path.getsize(self.file_path) > 0):
            with open(self.file_path, 'w') as file:
                json.dump(self.default_data, file, indent=4)

cache_handler = JsonFileHandler(
    CACHE_JSON,
    CACHE_CACHE,
    {"TRACKING": {}}
)

def read_cache_json() -> typing.Dict:
    return cache_handler.read()

def write_cache_json(data: typing.Dict) -> None:
    cache_handler.write(data)

def split_list_by_items(lst: list, num_items: int = 40) -> list:
    """
    Split a list into smaller lists, each containing a maximum of `num_items` items.

    This function takes a list `lst` and an optional parameter `num_items` (default is 40) that specifies the maximum number of items to include in each smaller list. It then returns a list of these smaller lists.

    Parameters:
    lst (list): The input list to be split.
    num_items (int, optional): The maximum number of items to include in each smaller list. Defaults to 40.

    Returns:
    list: A list of smaller lists, each containing a maximum of `num_items` items.
    """
    return [lst[i:i + num_items] for i in range(0, len(lst), num_items)]

def remove_non_alphanumeric(text: str) -> str:
    """
    Remove all non-alphanumeric characters from the input text.

    This function uses a regular expression to replace any character that is not a letter (a-z, A-Z) or a digit (0-9) with an empty string, effectively removing it from the input text.

    Parameters:
    text (str): The input text from which to remove non-alphanumeric characters.

    Returns:
    str: The input text with all non-alphanumeric characters removed.
    """
    return re.sub(r"[^a-zA-Z0-9]", "", text)

def map_courier_slug_to_code(courier_slug: str) -> int:
    """
    Map a courier slug to the corresponding courier code.

    This function takes a courier slug as input and searches the `courier_cache` global variable for a matching courier. If a match is found, the function returns the corresponding courier code. If no match is found or the input `courier_slug` is falsy (e.g., `None` or an empty string), the function returns 0.

    Parameters:
    courier_slug (str): The courier slug to map to a courier code.

    Returns:
    int: The courier code corresponding to the input slug, or 0 if no match is found or the input is falsy.
    """
    global courier_cache

    if not courier_slug:
        return 0

    for courier in courier_cache:
        if courier.get("_name").casefold() == courier_slug.casefold():
            return courier.get("key")

    return 0

def remap_tracking_data(tracking_data: list) -> list:
    """
    Remap the input tracking data to a format expected by the 17track API.

    This function takes a list of tracking data dictionaries, where each dictionary has a "num" and "slug" key, and remaps the data to a list of dictionaries with the following keys:
    - "num": The tracking number, with non-alphanumeric characters removed.
    - "fc": The courier code, obtained by mapping the courier slug to the corresponding code.
    - "sc": A constant value of 0.

    Parameters:
    tracking_data (list): A list of tracking data dictionaries, where each dictionary has a "num" and "slug" key.

    Returns:
    list: A list of remapped tracking data dictionaries.
    """
    remapped_tracking_data = []
    for tracking in tracking_data:
        remapped_tracking_data.append({
            "num": remove_non_alphanumeric(tracking.get("num")),
            "fc": map_courier_slug_to_code(tracking.get("slug")),
            "sc": 0,
        })
    return remapped_tracking_data

def capture_last_event_id(
    url: str = "https://m.17track.net/en/track-details#nums=1Z9999999999999999"
) -> typing.Optional[str]:
    """
    Capture the last event ID from the 17track website using Playwright.

    This function launches a headless Chromium browser, navigates to the specified URL, and intercepts all network requests made by the page. If a request is made to the 17track API endpoint for tracking information, the function extracts the "last-event-id" header value from the request and returns it.

    Parameters:
    url (str, optional): The URL to navigate to in the Chromium browser. Defaults to "https://m.17track.net/en/track-details#nums=1Z9999999999999999".

    Returns:
    Optional[str]: The captured last event ID, or `None` if it could not be obtained.
    """
    last_event_id = None
    with playwright.sync_api.sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
                "--disable-web-security",
                "--disable-features=IsolateOrigins",
                "--disable-site-isolation-trials",
                "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            ],
        )
        context = browser.new_context()
        page = context.new_page()

        def log_request(route, request):
            nonlocal last_event_id
            if not any(ext in request.url for ext in [".css", ".json", ".png", ".svg"]) and any(
                domain in request.url for domain in ["https://m.17track.net", "https://res.17track.net", "https://t.17track.net"]
            ):
                route.continue_()
                if request.url == "https://t.17track.net/restapi/track" and request.method == "POST":
                    captured_headers = request.headers
                    if captured_headers and "last-event-id" in captured_headers:
                        last_event_id = captured_headers["last-event-id"]
            else:
                route.abort()

        page.route("**/*", log_request)
        page.goto(url)
        browser.close()
    return last_event_id

def save_last_event_id(
    read_cache_json, 
    write_cache_json,
    last_event_id: str, 
    last_event_id_expiry: str
) -> None:
    """
    Save the last event ID and its expiration timestamp to a cache file.

    Parameters:
    last_event_id (str): The last event ID to save.
    last_event_id_expiry (str): The expiration timestamp of the last event ID, in the format "YYYY-MM-DD HH:MM:SS Z".
    """
    cache_data = read_cache_json()
    tracking_cache = cache_data.get("TRACKING", {})
    tracking_cache["last_event_id"] = last_event_id
    tracking_cache["last_event_id_expiry"] = last_event_id_expiry
    cache_data["TRACKING"] = tracking_cache
    write_cache_json(cache_data)

def check_last_event_id_expiry(read_cache_json, write_cache_json, hours: int = 1) -> str:
    """
    Check the expiration of the last event ID and, if necessary, update it.

    This function first loads the last event ID and its expiration timestamp from storage. If the last event ID is not available or has expired (based on the provided `hours` parameter), it calls the `capture_last_event_id` function to obtain a new last event ID, and then saves the new last event ID and its expiration timestamp to storage.

    Parameters:
    hours (int, optional): The number of hours after which the last event ID is considered expired. Defaults to 1.

    Returns:
    str: The current valid last event ID.
    """
    last_event_id, last_event_id_expiry = read_cache_json().get("TRACKING").get("last_event_id"), read_cache_json().get("TRACKING").get("last_event_id_expiry")

    if (
        not last_event_id
        or not last_event_id_expiry
        or datetime.datetime.now(tz=datetime.timezone.utc)
        >= datetime.datetime.strptime(
            last_event_id_expiry, "%Y-%m-%d %H:%M:%S %Z"
        ).replace(tzinfo=datetime.timezone.utc)
        + datetime.timedelta(hours=hours)
    ):
        print("[!] Last event ID not found or expired. Capturing new last event ID...")
        new_last_event_id = None
        while not new_last_event_id:
            print("[+] Capturing new last event ID...")
            new_last_event_id = capture_last_event_id()
        print(f"[+] New last event ID captured: {new_last_event_id}. Saving to cache...")
        save_last_event_id(
            read_cache_json,
            write_cache_json,
            new_last_event_id,
            datetime.datetime.now(tz=datetime.timezone.utc).strftime(
                "%Y-%m-%d %H:%M:%S %Z"
            ),
        )
        return new_last_event_id
    else:
        return last_event_id

def tracking(
    read_cache_json,
    write_cache_json,
    trackings: list, 
    headers: dict = {}, 
    proxies: dict = None
) -> dict:
    """
    Retrieve tracking information for the provided tracking numbers.

    Parameters:
    trackings (list): A list of tracking numbers, up to a maximum of 40.
    headers (dict, optional): A dictionary of custom headers to include in the request.
    proxies (dict, optional): A dictionary of proxy settings to use for the request.

    Returns:
    dict: A dictionary containing the tracking information for each provided tracking number.

    Raises:
    Exception: If the number of provided tracking numbers is invalid or if there is an error retrieving the tracking information.
    """
    if len(trackings) == 0 or len(trackings) > 40:
        raise Exception("invalid number of trackings provided")
    data = {}
    cache_data = read_cache_json()
    last_event_id, last_event_id_expiry = cache_data.get("last_event_id"), cache_data.get("last_event_id_expiry")
    if not last_event_id or not last_event_id_expiry:
        last_event_id = check_last_event_id_expiry(read_cache_json, write_cache_json)
    headers["Referer"] = "https://m.17track.net/"
    headers["User-Agent"] = cache_data["TRACKING"]["User_Agent"]
    headers["Last-Event-ID"] = last_event_id
    data["data"] = remap_tracking_data(trackings)
    print(f"[+] Preparing {len(trackings)} trackings to be tracked")
    if proxies:
        patch_proxy_connection()
        response = requests.post(
            "https://t.17track.net/restapi/track",
            json=data,
            headers=headers,
            timeout=10
        )
    else:
        print(f"[-] No proxy configured")
        response = requests.post(
            "https://t.17track.net/restapi/track", json=data, headers=headers
        )
    response_data = response.json()
    if response_data.get("msg") == "Ok":
        all_trackings_results = {}

        def parse_tracking_status(tracking_statuses: list) -> list:
            """
            Parse the tracking status information from the API response.

            Parameters:
            tracking_statuses (list): A list of dictionaries containing the raw tracking status information.

            Returns:
            list: A list of dictionaries, where each dictionary represents a parsed tracking status with the following keys:
                - time (int): The timestamp of the tracking status.
                - country (str): The country code of the tracking status.
                - location1 (str): The first location of the tracking status.
                - location2 (str): The second location of the tracking status.
                - status (str): The status message of the tracking status.
            """
            parsed_statuses = []
            for tracking_status in tracking_statuses:
                if not tracking_status:
                    continue
                tracking_status_time = tracking_status.get("a")
                tracking_status_country = tracking_status.get("b")
                tracking_status_location1 = tracking_status.get("c")
                tracking_status_location2 = tracking_status.get("d")
                tracking_status_message = tracking_status.get("z")

                # If location2 is present and location1 is not, move location2 to location1 and clear location2
                if tracking_status_location2 and not tracking_status_location1:
                    tracking_status_location1 = tracking_status_location2
                    tracking_status_location2 = ""

                parsed_statuses.append({
                    "time": tracking_status_time,
                    "country": tracking_status_country,
                    "location1": tracking_status_location1,
                    "location2": tracking_status_location2,
                    "status": tracking_status_message,
                })

            return parsed_statuses

        def parse_country_info(code: str) -> dict:
            """
            Parse the country information from the country cache.

            Parameters:
            code (str): The country code to look up.

            Returns:
            dict: A dictionary containing the country information, with the following keys:
                - mnemonic (str): The country mnemonic.
                - name (str): The country name.
                - code (str): The country code.
            
            If the country code is not found in the cache, the function returns `None`.
            """
            global country_cache

            for country in country_cache:
                if str(country.get("_numberKey")) == str(code):
                    return {
                        "mnemonic": country.get("_mnemonic"),
                        "name": country.get("_name"),
                        "code": country.get("_numberKey"),
                    }

            return None

        def parse_courier_info(code: str) -> dict:
            """
            Parse the courier information from the courier cache.

            Parameters:
            code (str): The courier code to look up.

            Returns:
            dict: A dictionary containing the courier information, with the following keys:
                - code (str): The courier code.
                - country (dict): A dictionary containing the country information for the courier, with the following keys:
                    - mnemonic (str): The country mnemonic.
                    - name (str): The country name.
                    - code (str): The country code.
                - contact (dict): A dictionary containing the courier contact information, with the following keys:
                    - email (str): The courier's email address.
                    - telephone (str): The courier's telephone number.
                    - website (str): The courier's website.
                - name (str): The courier name.
                - icon (str): The URL of the courier's logo image.
            
            If the courier code is not found in the cache, the function returns `None`.
            """
            global courier_cache

            for courier in courier_cache:
                if str(courier.get("key")) == str(code):
                    return {
                        "code": courier.get("key"),
                        "country": parse_country_info(courier.get("_country")),
                        "contact": {
                            "email": courier.get("_email"),
                            "telephone": courier.get("_tel"),
                            "website": courier.get("_url"),
                        },
                        "name": courier.get("_name"),
                        "icon": f"http://res.17track.net/asset/carrier/logo/120x120/{code}.png",
                    }

            return None

        def parse_status_info(code: int) -> dict:
            """
            Parse the status information from the status cache.

            Parameters:
            code (int): The status code to look up.

            Returns:
            dict: A dictionary containing the status information, with the following keys:
                - code (int): The status code.
                - name (str): The status name.
                - color (str): The status icon background color.
                - tips (str): The status tips.
            
            If the status code is not found in the cache, the function returns `None`.
            """
            global status_cache

            for status in status_cache:
                if int(status.get("key")) == int(code):
                    return {
                        "code": status.get("key"),
                        "name": status.get("_name"),
                        "color": status.get("_iconBgColor"),
                        "tips": status.get("_tips"),
                    }

            return None

        for tracking in response_data.get("dat", {}):
            tracking_number = tracking.get("no")
            tracking_delay = tracking.get("delay")
            if tracking.get("delay") == 1:
                for tracking in data["data"]:
                    all_trackings_results[tracking_number] = {
                        "tracking": tracking_number,
                        "delay": None,
                        "country1": None,
                        "country2": None,
                        "shorten_status": None,
                        "transit_time": None,
                        "courier1": None,
                        "courier2": None,
                        "all_status": None,
                        "lastest_status": None,
                        "picked_up": None,
                        "returned": None,
                        "retry_delay": True,
                    }
            else:
                tracking_info = tracking.get("track", {})
                if not tracking_info:
                    all_trackings_results[tracking_number] = {
                        "tracking": tracking_number,
                        "delay": None,
                        "country1": None,
                        "country2": None,
                        "shorten_status": None,
                        "transit_time": None,
                        "courier1": None,
                        "courier2": None,
                        "all_status": None,
                        "lastest_status": None,
                        "picked_up": None,
                        "returned": None,
                        "retry_delay": True,
                    }
                    continue
                tracking_country1 = tracking_info.get("b")
                tracking_country2 = tracking_info.get("c")
                if tracking_country1:
                    tracking_country1 = parse_country_info(tracking_country1)
                else:
                    tracking_country1 = None
                if tracking_country2:
                    tracking_country2 = parse_country_info(tracking_country2)
                else:
                    tracking_country2 = None
                tracking_shorten_status = tracking_info.get("e")
                if tracking_shorten_status or tracking_shorten_status == 0:
                    tracking_shorten_status = parse_status_info(tracking_shorten_status)
                else:
                    tracking_shorten_status = {}
                tracking_transit_time = tracking_info.get("f")
                if tracking_transit_time < 0:
                    tracking_transit_time = None
                tracking_courier1 = tracking_info.get("w1")
                tracking_courier2 = tracking_info.get("w2")
                if tracking_courier1:
                    tracking_courier1 = parse_courier_info(tracking_courier1)
                else:
                    tracking_courier1 = None
                if tracking_courier2:
                    tracking_courier2 = parse_courier_info(tracking_courier2)
                else:
                    tracking_courier2 = None
                all_tracking_status = parse_tracking_status(tracking_info.get("z1"))
                lastest_tracking_status = parse_tracking_status(
                    [tracking_info.get("z0")]
                )
                if len(lastest_tracking_status) == 1:
                    lastest_tracking_status = lastest_tracking_status[0]
                else:
                    lastest_tracking_status = {}
                tracking_picked_up = tracking_info.get("zex", {}).get("pickup")
                if tracking_picked_up:
                    tracking_picked_up = True
                else:
                    tracking_picked_up = False
                tracking_returned = tracking_info.get("zex", {}).get("return")
                if tracking_returned:
                    tracking_returned = True
                else:
                    tracking_returned = False
                all_trackings_results[tracking_number] = {
                    "tracking": tracking_number,
                    "delay": tracking_delay,
                    "country1": tracking_country1,
                    "country2": tracking_country2,
                    "shorten_status": tracking_shorten_status,
                    "transit_time": tracking_transit_time,
                    "courier1": tracking_courier1,
                    "courier2": tracking_courier2,
                    "all_status": all_tracking_status,
                    "lastest_status": lastest_tracking_status,
                    "picked_up": tracking_picked_up,
                    "returned": tracking_returned,
                    "retry_delay": False,
                }
        return all_trackings_results
    elif response_data.get("msg") == "numNon":
        raise Exception(f"invalid tracking number provided: {response_data.get('msg')}")
    else:
        raise Exception(
            f"error retrieving tracking information: {response_data.get('msg')}"
        )

# Global state as dict for atomic updates
daemon_states = {
    "is_track_rotating": {"status": False},
}

def rotate_daemon(exe_type, interval_seconds=15) -> None:
    global daemon_states
    exe_type_normalized = exe_type.lower().strip()
    state_key = f"is_{exe_type_normalized}_rotating"
    
    # Make sure the state exists
    if state_key not in daemon_states:
        daemon_states[state_key] = {"status": False}
    
    print(f"[*] Starting daemon for {exe_type_normalized}")
    
    try:
        while True:
            #with daemon_lock:
            if daemon_states[state_key]["status"]:
                print(f"[!] Daemon already running for {exe_type_normalized}. Skipping cycle.")
                time.sleep(1)
                continue
                
            try:
                daemon_states[state_key]["status"] = True
                if "track" in exe_type_normalized:
                    print("[+] Checking last event id expiry.")
                    check_last_event_id_expiry(
                        read_cache_json,
                        write_cache_json,
                        cache_handler.get("TRACKING", {}).get("TRACK_REFRESH_HOUR")
                    )
                else:
                    print(f"[!] Unknown daemon type: {exe_type_normalized}")
                    print(f"[!] exe_type: {exe_type}, normalized: {exe_type_normalized}")
                
            except Exception as e:
                print(f"[!] Error in rotate_daemon {exe_type_normalized}: {e}")
                import traceback
                print(traceback.format_exc())
            finally:
                #print(f"[DEBUG] Setting status to False for {exe_type_normalized}")
                daemon_states[state_key]["status"] = False
                    
            #print(f"[DEBUG] Sleep for {interval_seconds} seconds for {exe_type_normalized}")
            time.sleep(interval_seconds)
    except Exception as e:
        print(f"[!] Fatal error in rotate_daemon {exe_type_normalized}: {e}")

def run_daemon_loop() -> None:
    """Master daemon that starts all worker threads"""
    try:
        print("[+] Starting master daemon loop...")
        
        # Start track rotation daemon
        threading.Thread(
            target=rotate_daemon,
            args=("Track", 3600),
            daemon=True
        ).start()

        while True:
            time.sleep(60)
            
    except Exception as e:
        print(f"[!] Error in master daemon: {e}.")


def pick_random_proxy(proxies):
    if proxies:
        return random.choice(proxies)
    return None


app = flask.Flask(__name__)

@app.route("/v1/package/information", methods=["GET"])
def api_package_info() -> typing.Tuple[flask.Response, int]:
    try:
        data = flask.request.json
        tracking_information = data.get("tracking_information", None)
        if not tracking_information:
            missing_fields = []
            if not tracking_information:
                missing_fields.append("tracking_information")
            return (
                flask.jsonify(
                    status="error",
                    message=f"failed to fetch package: missing field(s): {', '.join(missing_fields)}",
                ),
                404,
            )   
        mapped_tracking_information = []
        for item in tracking_information:
            if "tracking" not in item:
                return (
                    flask.jsonify(
                        status="error",
                        message="failed to fetch package: tracking not specified",
                    ),
                    404,
                )
            tracking_mapping = {
                "num": item.get("tracking", ""),
                "slug": item.get("slug", 0),
            }
            mapped_tracking_information.append(tracking_mapping)

        tracking_proxies = read_cache_json().get("TRACKING", {}).get("TRACKING_PROXY", [])
        random_proxy = pick_random_proxy(tracking_proxies)
        tracking_status_information = tracking(
            read_cache_json=read_cache_json,
            write_cache_json=write_cache_json,
            trackings=mapped_tracking_information,
            proxies={"all": [random_proxy]}
        )
        if not tracking_status_information:
            return (
                flask.jsonify(
                    status="error",
                    message="failed to fetch package: tracking information not found",
                ),
                404,
            )
        return (
            flask.jsonify(
                status="success",
                message="successfully fetched packages",
                data=tracking_status_information,
            ),
            200,
        )
    except Exception as e:
        return flask.jsonify(status="error", message=f"failed to fetch packages: {e}"), 500

print("[*] Starting server...")
if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5000, debug=True)
