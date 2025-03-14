import csv
import time
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

TRACKING_NUMBERS = ['9505526257563359041741', '9505529654165284747837', '9505540988439458236403', '9505503155015623679838', '9505574096826851721590', '9505565157280396649289', '9505576368217530488541', '9505513890580585866510', '9505524426270467822509', '9505580910205349076060', '9505533064087426219593', '9505573214248357813758', '9505516564138860768418', '9505585211658624753674', '9505587517174694184644', '9505531059020584174971', '9505545660523169983540', '9505539055435518194152', '9505510117525142484267', '9505566190320504588634', '9505598284672557863107', '9505512927463259142485', '9505559071406533234587', '9505503181301486071342', '9505569625722444333930', '9505540438172775503826', '9505501974019520002693', '9505568575646453942473', '9505564605649186943405', '9505592752677248355873', '9505563957882538985996', '9505526731219522801007', '9505509588643846036327', '9505590006718755199100', '9505502237990911085385', '9505517404013016016222', '9505510678986855434660', '9505567973631035504362', '9505536491797038980125', '9505526346060036819066', '9505501531476781197787', '9505522920416039885306', '9505582208150989360573', '9505516376645821016404', '9505581846475120625043', '9505592301642875905791', '9505585172600061815868', '9505591090111273448143', '9505532812024180024584', '9505504211566921977314', '9505538355775966292544', '9505532152698587589462', '9505537702266354077784', '9505531540342633679044', '9505578314419042734236', '9505511767691073880860', '9505592977883856009450', '9505534485339929990759', '9505533561924539617879', '9505500560438129378246', '9505566153573891321547', '9505553205501919628301', '9505548604896321203448', '9505518543645607652158', '9505542978716759784374', '9505581749489636023604', '9505540018770164756206', '9505571007272740682124', '9505550424384680899604', '9505550797263861738808', '9505598108656702885436', '9505588483068815247916', '9505536361635503163614', '9505507556479947125298', '9505501285246494035478', '9505587929973499708113', '9505575863211411461640', '9505563215279614401258', '9505504880421077178029', '9505582683693951470315', '9505596430900507454895', '9505579286712862609667', '9505585197482509774154', '9505592883674209721967', '9505506499177318301317', '9505508108145239583674', '9505591350456325895155', '9505535640242858189694', '9505528547459456468694', '9505559295542434716437', '9505579241023396393555', '9505505655794807967600', '9505539531567403106454']

OUTPUT_CSV = "usps_tracking_results.csv"

def chunk_list(lst, chunk_size=30):
    for i in range(0, len(lst), chunk_size):
        yield lst[i:i + chunk_size]

def generate_tracking_url(tracking_numbers):
    joined_numbers = '%2C'.join(tracking_numbers)
    return f"https://tools.usps.com/go/TrackConfirmAction?tRef=fullpage&tLc=5&tLabels={joined_numbers}&tABt=true"

def configure_selenium():
    options = webdriver.ChromeOptions()
    options.add_argument('--start-maximized')
    return options

def fetch_tracking_data():
    results = []
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=configure_selenium())

    for batch in chunk_list(TRACKING_NUMBERS):
        url = generate_tracking_url(batch)
        print(f"Fetching URL: {url}")
        driver.get(url)

        try:
            WebDriverWait(driver, 20).until(
                EC.presence_of_all_elements_located((By.CLASS_NAME, "tracking-result"))
            )

            tracking_elements = driver.find_elements(By.CLASS_NAME, "tracking-result")

            if not tracking_elements:
                print("[Warning] No tracking elements found, retrying once...")
                driver.refresh()
                time.sleep(5)
                tracking_elements = driver.find_elements(By.CLASS_NAME, "tracking-result")

            for element in tracking_elements:
                try:
                    tracking_number = element.find_element(By.CLASS_NAME, "tracking-number").text.strip()
                    status = element.find_element(By.CLASS_NAME, "tb-status").text.strip()
                    details = element.find_element(By.CLASS_NAME, "tb-status-detail").text.strip()
                    date_time = element.find_element(By.CLASS_NAME, "tb-date").text.strip()

                    print(f"Tracking Number: {tracking_number}")
                    print(f"Status: {status}")
                    print(f"Details: {details}")
                    print(f"Date & Time: {date_time}\n")

                    results.append([tracking_number, status, details, date_time])

                except Exception as inner_e:
                    print(f"[Error parsing element]: {inner_e}")
                    continue

        except Exception as e:
            print(f"[ERROR loading batch]: {e}. Retrying once...")
            driver.refresh()
            time.sleep(5)
            continue

    driver.quit()
    save_results_to_csv(results)

def save_results_to_csv(results):
    with open(OUTPUT_CSV, "w", newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        writer.writerow(["Tracking Number", "Status", "Details", "Date & Time"])
        writer.writerows(results)

    print(f"\nResults successfully saved to {OUTPUT_CSV}")

if __name__ == "__main__":
    fetch_tracking_data()