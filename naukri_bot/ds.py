import json
import logging
import os
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchWindowException, TimeoutException, WebDriverException
import time
from datetime import datetime
import traceback
from selenium.webdriver.chrome.service import Service
import schedule

# Set up logging
logging.basicConfig(
    filename='/Users/ashutoshsharma/Downloads/naukri_bot/naukri_update.log',
    level=logging.INFO,
    format='%(asctime)s:%(levelname)s:%(message)s'
)

def load_credentials():
    """Load Naukri credentials from a JSON file."""
    with open('/Users/ashutoshsharma/Downloads/naukri_bot/credentials.json', 'r') as f:
        credentials = json.load(f)
    return credentials['username'], credentials['password']

def click_element(driver, element):
    """Attempts to click the element once."""
    try:
        driver.execute_script("arguments[0].click();", element)
        logging.info("Clicked the element successfully.")
    except Exception as e:
        logging.error(f"Failed to click the element: {e}")

def scroll_to_element(driver, element):
    """Scrolls the page to the given element."""
    driver.execute_script("arguments[0].scrollIntoView(true);", element)
    time.sleep(1)

def login_to_naukri(driver, username, password):
    try:
        driver.get('https://www.naukri.com/nlogin/login')
        time.sleep(5)

        # Enter username and password
        email_input = driver.find_element(By.ID, 'usernameField')
        email_input.clear()
        email_input.send_keys(username)

        password_input = driver.find_element(By.ID, 'passwordField')
        password_input.clear()
        password_input.send_keys(password)
        password_input.send_keys(Keys.RETURN)
        time.sleep(10)  # Wait for login

        logging.info("Login successful")

    except Exception as e:
        logging.error(f"Error during login: {e}")

def update_naukri_profile(driver):
    try:
        logging.info("Navigating to the profile update page.")
        driver.get('https://www.naukri.com/mnjuser/profile?id=&altresid')
        time.sleep(20)

        edit_button = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable((By.XPATH, "//span[contains(@class, 'edit') and text()='editOneTheme']"))
        )
        scroll_to_element(driver, edit_button)
        click_element(driver, edit_button)

        input_field = WebDriverWait(driver, 20).until(
            EC.visibility_of_element_located((By.XPATH, "//textarea[@id='resumeHeadlineTxt']"))
        )
        logging.info("Found the input field for resume headline.")
        
        current_value = input_field.get_attribute('value')

        # Toggle dot at the end of the input
        if current_value.endswith("."):
            # Remove the dot if it exists
            input_field.clear()
            input_field.send_keys(current_value[:-1])
            logging.info("Removed the dot from the input field.")
        else:
            # Add the dot if it doesn't exist
            input_field.clear()
            input_field.send_keys(current_value + ".")
            logging.info("Added a dot to the input field.")

        save_button = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable((By.XPATH, "//button[@class='btn-dark-ot' and @type='submit']"))
        )
        click_element(driver, save_button)

        logging.info("Profile updated successfully.")
        update_resume(driver)

    except Exception as e:
        logging.error(f"Error during profile update: {e}")
        logging.error(f"Full traceback: {traceback.format_exc()}")
    finally:
        driver.quit()

def update_resume(driver):
    """Uploads a new resume to the profile."""
    try:
        update_button = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable((By.XPATH, "//input[@type='button' and @value='Update resume' and contains(@class, 'dummyUpload')]"))
        )
        file_input = driver.find_element(By.XPATH, "//input[@type='file']")
        resume_file_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "Ashutosh_Sharma_AI_Engineer_Resume.docx")
        file_input.send_keys(resume_file_path)
        time.sleep(10)
        logging.info("Resume uploaded successfully.")
    except Exception as e:
        logging.error(f"Error during resume upload: {e}")
        logging.error(f"Full traceback: {traceback.format_exc()}")

def main():
    # Load credentials
    username, password = load_credentials()

    # Set up Chrome options for headless mode and bypass detection
    options = Options()
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36")
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--incognito')
    #options.add_argument('--headless')  # Uncomment if you want to run in headless mode

    driver_path = '/Users/ashutoshsharma/Downloads/naukri_bot/chromedriver'  # Update with your ChromeDriver path
    service = Service(driver_path)
    driver = webdriver.Chrome(service=service, options=options)

    try:
        login_to_naukri(driver, username, password)
        update_naukri_profile(driver)
    finally:
        driver.quit()

# Scheduling logic
schedule.every(5).minutes.do(main)

if __name__ == "__main__":
    logging.info("Scheduler started. Running the task every 2 minutes.")
    main()  # Run once immediately
    while True:
        schedule.run_pending()
        time.sleep(1)  # Prevent high CPU usage