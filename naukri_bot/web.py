"""Recursively scraping specific URLs and downloading .htm files as PDFs using httpx."""

import httpx
from urllib.parse import urlparse, urljoin, urlunparse
from fastapi import HTTPException
from bs4 import BeautifulSoup
from loguru import logger
import re
import tldextract
from typing import Set, Dict, Optional
from weasyprint import HTML, CSS
import os

SKIP_FILE_TYPES = r"\.(pdf|docx?|xls?|xlsx?|pptx?|txt|csv|jpg|jpeg|png|gif|bmp|svg)$"
MIN_WORDS_PER_LINE = 2
OUTPUT_DIR = "downloaded_pdfs"  # Using a different output directory

class WebRecursiveWithPDFHttpx:
    """A class for recursively scraping specific URLs and downloading .htm files as PDFs using httpx."""

    def __init__(self, url: str, max_urls: int = 30, support_http: bool = False):
        self.total_urls_visited = 0
        self.url = self.normalize_url(url, support_http=support_http)
        self.domain_name = urlparse(self.url).netloc
        self.max_urls = max_urls
        self.internal_urls: Set[str] = set()
        self.external_urls: Set[str] = set()
        self.scrapped_data: Dict[str, str] = {}
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        self.client = httpx.Client()

    def normalize_url(self, url: str, support_http: bool = False) -> str:
        """Normalizes the URL format for standardization."""
        parsed_url = urlparse(url)
        scheme = parsed_url.scheme if parsed_url.scheme else ("http" if support_http else "https")
        netloc = parsed_url.netloc or parsed_url.path
        if not netloc.startswith("www.") and netloc:
            netloc = "www." + netloc
        return urlunparse((scheme, netloc, parsed_url.path, parsed_url.params, parsed_url.query, parsed_url.fragment))

    @staticmethod
    def is_valid(url: str) -> bool:
        """Checks whether a URL is valid."""
        try:
            result = urlparse(url)
            return bool(result.scheme in ["http", "https"] and result.netloc)
        except Exception as e:
            logger.error(f"Invalid URL: {e}")
            return False

    @staticmethod
    def _is_valid_href(href: str) -> bool:
        """Checks if a href link is valid and not a file we want to skip."""
        try:
            if href.strip() in ("", "#") or re.search(SKIP_FILE_TYPES, href, re.IGNORECASE):
                return False
            return True
        except Exception as e:
            logger.error(f"Invalid href: {e}")
            return False

    def _get_all_website_links(self, url: str) -> Optional[Set[str]]:
        """Extracts all valid URLs from the given webpage."""
        try:
            response = self.client.get(url)
            response.raise_for_status()
            if "text/html" not in response.headers.get("Content-Type", ""):
                logger.warning(f"Content type is not HTML for URL: {url}")
                return None

            soup = BeautifulSoup(response.content, "html.parser")
            internal_urls_on_page: set[str] = set()
            for a_tag in soup.findAll("a"):
                href = a_tag.attrs.get("href")
                if not href or not self._is_valid_href(href):
                    continue

                full_url = urljoin(url, href)
                parsed_href = urlparse(full_url)
                normalized_url = f"{parsed_href.scheme}://{parsed_href.netloc}{parsed_href.path}"

                if not self.is_valid(normalized_url):
                    logger.warning(f"Invalid URL found: {normalized_url} on {url}")
                    continue

                if self._is_same_root_domain(self.url, normalized_url):
                    internal_urls_on_page.add(normalized_url)
                elif normalized_url not in self.external_urls:
                    logger.info(f"External URL found: {normalized_url} on {url}")
                    self.external_urls.add(normalized_url)

            return internal_urls_on_page
        except httpx.RequestError as e:
            logger.error(f"Error scraping URL {url}: {e}")
            return None

    @staticmethod
    def _is_same_root_domain(base_url: str, current_url: str) -> bool:
        """Compares if two URLs belong to the same root domain."""
        base_domain = tldextract.extract(base_url)
        current_domain = tldextract.extract(current_url)
        return base_domain.domain == current_domain.domain and base_domain.suffix == current_domain.suffix

    def _download_as_pdf(self, url: str, content: bytes):
        """Downloads the content of a URL as a PDF file."""
        try:
            parsed_url = urlparse(url)
            filename = f"{parsed_url.netloc}{parsed_url.path.replace('/', '_')}.pdf"
            filepath = os.path.join(OUTPUT_DIR, filename)
            HTML(string=content.decode('utf-8', errors='ignore')).write_pdf(filepath)
            logger.info(f"Downloaded {url} as {filepath}")
        except Exception as e:
            logger.error(f"Error downloading {url} as PDF: {e}")

    def load_full_web(self, start_url: Optional[str] = None, max_urls: Optional[int] = None) -> Dict[str, str]:
        """Recursively crawls specific sub-links and downloads .htm as PDFs using httpx."""
        if start_url is None:
            start_url = self.url
        max_urls = max_urls or self.max_urls
        queue = {start_url}
        visited = set()
        target_sublinks = set()

        logger.info(f"Crawling starting from: {start_url}")

        # First, get the main page and extract the target sub-links
        try:
            response = self.client.get(start_url)
            response.raise_for_status()
            if "text/html" in response.headers.get("Content-Type", ""):
                soup = BeautifulSoup(response.content, "html.parser")
                self.scrapped_data[start_url] = self._extract_body_text(soup) or " "
                if start_url.endswith((".htm", ".html")):
                    self._download_as_pdf(start_url, response.content)

                # Identify the specific sub-links based on their text content
                sublink_texts = ["General Rules", "ABAP-Specific Rules", "Structure and Style", "Architecture", "Robust ABAP"]
                for link in soup.find_all('a'):
                    if link.string and link.string.strip() in sublink_texts:
                        href = link.get('href')
                        if href and self._is_valid_href(href):
                            full_url = urljoin(start_url, href)
                            if self._is_same_root_domain(start_url, full_url):
                                target_sublinks.add(full_url)
                                logger.info(f"Found target sub-link: {full_url}")

                # Add the target sub-links to the queue for crawling
                for sublink in target_sublinks:
                    if sublink not in visited:
                        queue.add(sublink)

            else:
                logger.warning(f"Skipping non-HTML content: {start_url}")

        except httpx.RequestError as e:
            logger.error(f"Error processing initial URL {start_url}: {e}")
            return self.scrapped_data
        except Exception as e:
            logger.error(f"An unexpected error occurred while processing {start_url}: {e}")
            return self.scrapped_data

        while queue and self.total_urls_visited < max_urls:
            current_url = queue.pop()
            if current_url in visited:
                continue
            visited.add(current_url)
            self.total_urls_visited += 1
            logger.info(f"Crawling sub-link: {current_url} ({self.total_urls_visited}/{max_urls})")

            try:
                response = self.client.get(current_url)
                response.raise_for_status()
                if "text/html" in response.headers.get("Content-Type", ""):
                    soup = BeautifulSoup(response.content, "html.parser")
                    self.scrapped_data[current_url] = self._extract_body_text(soup) or " "
                    if current_url.endswith((".htm", ".html")):
                        self._download_as_pdf(current_url, response.content)

                    # Optional: If you want to go deeper into links within these sub-pages
                    # links_on_page = self._get_all_website_links(current_url)
                    # if links_on_page:
                    #     for link in links_on_page:
                    #         if link not in visited and self._is_same_root_domain(self.url, link) and self.total_urls_visited < max_urls:
                    #             queue.add(link)
                else:
                    logger.warning(f"Skipping non-HTML content: {current_url}")

            except httpx.RequestError as e:
                logger.error(f"Error processing URL {current_url}: {e}")
            except Exception as e:
                logger.error(f"An unexpected error occurred while processing {current_url}: {e}")

        logger.info(f"Crawling finished. Visited {len(visited)} URLs.")
        return self.scrapped_data

    def load_single_page(self) -> Dict[str, str]:
        """Scrapes only the given URL and downloads it as PDF if it's an .htm file using httpx."""
        logger.info(f"[*] Scraping: {self.url}")
        try:
            response = self.client.get(self.url)
            response.raise_for_status()
            if "text/html" in response.headers.get("Content-Type", ""):
                soup = BeautifulSoup(response.content, "html.parser")
                self.scrapped_data[self.url] = self._extract_body_text(soup) or " "
                if self.url.endswith((".htm", ".html")):
                    self._download_as_pdf(self.url, response.content)
                self._get_all_website_links(self.url)  # Still get links for single page info
            else:
                logger.warning(f"Skipping non-HTML content: {self.url}")
        except httpx.RequestError as e:
            logger.error(f"Error scraping {self.url}: {e}")
        return self.scrapped_data

    @staticmethod
    def _extract_body_text(soup: BeautifulSoup) -> Optional[str]:
        """Extracts the visible text from the webpage."""
        try:
            body_tag = soup.body or soup.new_tag("body")
            for element in body_tag(["head", "script", "style", "noscript", "iframe"]):
                element.extract()

            body_text = body_tag.get_text(separator="\n", strip=True)
            return "\n".join(
                line.strip().replace("  ", " ")
                for line in body_text.split("\n")
                if len(line.split()) >= MIN_WORDS_PER_LINE
            )
        except Exception as e:
            logger.error(f"Error extracting body text: {e}")
            return None


if __name__ == "__main__":
    target_url = "https://www.help.sap.com/doc/abapdocu_752_index_htm/7.52/en-US/abenabap_pgl.htm"
    crawler = WebRecursiveWithPDFHttpx(url=target_url, max_urls=10)
    scraped_data = crawler.load_full_web()

    print("Scraped Data:")
    for url, text in scraped_data.items():
        print(f"\nURL: {url}")
        # print(f"Text: {text[:200]}...")

    print(f"\nInternal URLs found: {crawler.internal_urls}")
    print(f"\nExternal URLs found: {crawler.external_urls}")
    print(f"\nDownloaded PDFs are saved in the '{OUTPUT_DIR}' directory.")