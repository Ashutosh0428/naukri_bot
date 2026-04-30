import json
import logging
import os
import time
import traceback
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchWindowException, TimeoutException, WebDriverException

# Set up logging
logging.basicConfig(
    filename='naukri_update.log',
    level=logging.INFO,
    format='%(asctime)s:%(levelname)s:%(message)s'
)

def log_and_print(message, level="info"):
    """Logs and prints messages."""
    print(message)
    if level == "info":
        logging.info(message)
    elif level == "error":
        logging.error(message)

def load_credentials():
    """Loads Naukri credentials from credentials.json."""
    with open('credentials.json', 'r') as f:
        credentials = json.load(f)
    return credentials['username'], credentials['password'], credentials['resume_path']

def click_element(driver, element):
    """Safely clicks an element."""
    try:
        driver.execute_script("arguments[0].click();", element)
        log_and_print("Clicked element successfully.")
    except Exception as e:
        log_and_print(f"Failed to click element: {e}", "error")

def scroll_to_element(driver, element):
    """Scrolls to an element in the browser."""
    driver.execute_script("arguments[0].scrollIntoView(true);", element)
    time.sleep(1)

def login_to_naukri(driver, username, password):
    """Logs into Naukri.com."""
    try:
        log_and_print("Opening Naukri login page...")
        driver.get('https://www.naukri.com/nlogin/login')
        time.sleep(5)

        email_input = driver.find_element(By.ID, 'usernameField')
        email_input.clear()
        email_input.send_keys(username)

        password_input = driver.find_element(By.ID, 'passwordField')
        password_input.clear()
        password_input.send_keys(password)
        password_input.send_keys(Keys.RETURN)
        time.sleep(10)

        log_and_print("Login successful!")
    except Exception as e:
        log_and_print(f"Login failed: {e}", "error")

def update_naukri_profile(driver):
    """Updates the Naukri profile resume headline."""
    try:
        log_and_print("Navigating to profile update page...")
        driver.get('https://www.naukri.com/mnjuser/profile?id=&altresid')
        time.sleep(10)

        edit_button = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable((By.XPATH, "//span[contains(@class, 'edit') and text()='editOneTheme']"))
        )
        scroll_to_element(driver, edit_button)
        click_element(driver, edit_button)

        input_field = WebDriverWait(driver, 20).until(
            EC.visibility_of_element_located((By.XPATH, "//textarea[@id='resumeHeadlineTxt']"))
        )

        current_value = input_field.get_attribute('value')
        if current_value.endswith("."):
            input_field.clear()
            input_field.send_keys(current_value[:-1])
            log_and_print("Removed dot from headline.")
        else:
            input_field.clear()
            input_field.send_keys(current_value + ".")
            log_and_print("Added dot to headline.")

        save_button = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable((By.XPATH, "//button[@class='btn-dark-ot' and @type='submit']"))
        )
        click_element(driver, save_button)

        log_and_print("Profile headline updated successfully.")
        update_resume(driver)

    except Exception as e:
        log_and_print(f"Profile update failed: {e}", "error")
        log_and_print(traceback.format_exc(), "error")
    finally:
        driver.quit()

def update_resume(driver):
    """Uploads a new resume to Naukri profile."""
    try:
        update_button = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable((By.XPATH, "//input[@type='button' and @value='Update resume' and contains(@class, 'dummyUpload')]"))
        )
        file_input = driver.find_element(By.XPATH, "//input[@type='file']")
        resume_file_path = os.path.abspath("ASHUTOSH-SHARMA-resume.pdf")
        file_input.send_keys(resume_file_path)
        time.sleep(10)
        log_and_print("Resume uploaded successfully.")
    except Exception as e:
        log_and_print(f"Resume upload failed: {e}", "error")
        log_and_print(traceback.format_exc(), "error")

def main():
    """Main function to execute the script."""
    log_and_print("Starting Naukri bot...")

    username, password, resume_path = load_credentials()

    # Set up Chrome options
    options = Options()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--incognito")
    options.add_argument("--headless")  # Run in headless mode
    options.add_argument("--user-data-dir=/tmp/selenium_user_data")  # Unique user profile
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36")

    # Optional: Use a Proxy if needed
    PROXY = "http://138.201.140.40:3128"  # Example working proxy
    options.add_argument(f'--proxy-server={PROXY}')

    # ChromeDriver path
    driver_path = '/usr/local/bin/chromedriver'
    service = Service(driver_path)

    try:
        log_and_print("Initializing WebDriver...")
        driver = webdriver.Chrome(service=service, options=options)
    except Exception as e:
        log_and_print(f"WebDriver initialization failed: {e}", "error")
        log_and_print(traceback.format_exc(), "error")
        return

    login_to_naukri(driver, username, password)
    update_naukri_profile(driver)
    log_and_print("Task completed successfully!")

if __name__ == "__main__":
    main()
