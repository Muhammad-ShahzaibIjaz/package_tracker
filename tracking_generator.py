import requests
import json
import csv
import os
import time


# CONSTANTS
START_TRACKING_NUMBER = 9405503699300737000270
TRACKING_API_URL = "http://185.17.0.0:5000/v1/package/information"
CACHE_FILE = "cache.json"
CSV_FILE = "filtered_tracking_numbers.csv"
BATCH_SIZE = 30
DELAY_SECONDS = 10
MAX_RETRIES = 5


def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r") as file:
            return json.load(file)
    
    return None

def save_cache(cache):
    with open(CACHE_FILE, "w") as file:
        json.dump(cache, file, indent=4)


def fetch_tracking_info(tracking_numbers):
    payload = {
        "tracking_information" : [{"tracking": str(num)} for num in tracking_numbers]
    }

    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(TRACKING_API_URL, json=payload)

            if response.status_code == 200:
                return response.json()
            else:
                print(f"[!] - Attempt {attempt + 1}: Failed to fetch tracking info: {response.status_code}")

                if response.status_code == 500:
                    print(f"[!] - Server error (500). Retrying...")
                    time.sleep(DELAY_SECONDS*54)

        except Exception as e:
            print(f"[!] - Attempt {attempt + 1}: Error fetching tracking info: {e}")
            time.sleep(DELAY_SECONDS)
    return None
    
def filter_tracking_numbers(tracking_info):
    filtered_data = []
    if not tracking_info or not tracking_info.get("data"):
        print("[!] No tracking data found in the API response.")
        return filtered_data

    for tracking_number, data in tracking_info["data"].items():
        try:
            if not data:
                print(f"[!] No data found for tracking number {tracking_number}")
                continue

            status = data.get("shorten_status", {}).get("name", "").lower()
            if status in ["pre-shipment", "expired"]:
                filtered_data.append({
                    "tracking_number": tracking_number,
                    "status": status,
                    "data": data
                })
        except AttributeError as e:
            print(f"[!] Error processing tracking number {tracking_number}: {e}")
        except Exception as e:
            print(f"[!] Unexpected error processing tracking number {tracking_number}: {e}")
    
    return filtered_data

def save_to_csv(filtered_data):
    file_exists = os.path.exists(CSV_FILE)
    with open(CSV_FILE, mode="a", newline="") as file:
        writer = csv.writer(file)
        if not file_exists:
            writer.writerow(["Tracking Number", "Status", "Data"])
        for item in filtered_data:
            writer.writerow([item["tracking_number"], item["status"], json.dumps(item["data"])])



def main():
    global cache
    cache = load_cache()
    last_tracking_number = cache.get("last_tracking_number", START_TRACKING_NUMBER)
    current_tracking_number = last_tracking_number

    while True:
        tracking_numbers = [current_tracking_number + i for i in range(BATCH_SIZE)]
        current_tracking_number += BATCH_SIZE


        print(f"[+] Waiting for {DELAY_SECONDS} seconds before the batch...")
        time.sleep(DELAY_SECONDS)

        tracking_info = fetch_tracking_info(tracking_numbers)

        cache["last_tracking_number"] = current_tracking_number
        save_cache(cache)
        print(f"[+] - Last processed tracking number: {current_tracking_number}")

        if not tracking_info:
            break

        filtered_data = filter_tracking_numbers(tracking_info)
        if not filtered_data:
            print("[!] - No matching tracking numbers in this batch.")
            continue
        
        save_to_csv(filtered_data)
        print(f"[+] - Saved {len(filtered_data)} tracking numbers to CSV.")


if __name__ == "__main__":
    main()