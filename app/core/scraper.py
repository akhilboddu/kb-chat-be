from playwright.async_api import async_playwright, Error as PlaywrightError, Page, Route, Request
from langchain_deepseek.chat_models import ChatDeepSeek
from langchain_google_genai import ChatGoogleGenerativeAI
import json
import asyncio
import time
import os
import logging
import re
from datetime import datetime
from typing import Dict, List, Any, Set, Tuple, Optional
from urllib.parse import urljoin, urlparse
from dotenv import load_dotenv
from app.core.data_processor import chunk_text

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

load_dotenv()

# Create results directory if it doesn't exist
RESULTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "results")
os.makedirs(RESULTS_DIR, exist_ok=True)

# --- Define the missing helper function --- 
def extract_json_from_markdown(markdown_string: str) -> Dict[str, Any]:
    """Extracts a JSON object from a Markdown string containing ```json ... ```."""
    try:
        # Regex to find JSON block within triple backticks
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", markdown_string, re.DOTALL | re.IGNORECASE)
        
        if match:
            json_string = match.group(1)
        else:
            # If no backticks, assume the entire string might be JSON (or partial)
            # Find the first '{' and last '}' to crudely extract potential JSON
            start_index = markdown_string.find('{')
            end_index = markdown_string.rfind('}')
            if start_index != -1 and end_index != -1 and end_index > start_index:
                json_string = markdown_string[start_index:end_index+1]
            else:
                 # Fallback: try parsing the whole string directly if no clear markers
                 json_string = markdown_string

        # Clean the extracted string (remove potential leading/trailing non-JSON chars)
        json_string = json_string.strip()

        # Parse the JSON string
        data = json.loads(json_string)
        return data
    except json.JSONDecodeError as e:
        error_msg = f"Failed to decode JSON: {e}. String was: '{json_string[:200]}...' # Log partial string"
        logger.error(error_msg)
        return {"error": error_msg, "original_content": markdown_string} # Return error dict
    except Exception as e:
        error_msg = f"Unexpected error extracting JSON: {e}"
        logger.error(error_msg)
        return {"error": error_msg, "original_content": markdown_string}

# --- Default Configuration --- 
default_config = {
    "BLOCK_RESOURCES": True,
    "TARGET_CONTENT_SELECTORS": [
        "main", "article", ".content", "#content", ".main-content", "#main-content", "body"
    ],
    "NAVIGATION_SELECTORS": [
        "header", "nav", ".nav", "#nav", ".navigation", "#navigation",
        "footer", ".footer", "#footer", ".main-nav", ".primary-nav", ".menu", "#menu"
    ],
    "MAX_INTERNAL_PAGES": 15,
    "MAX_CONCURRENT_SCRAPES": 5,
    "MAX_CONTENT_LENGTH": 10000,
    "PAGE_LOAD_TIMEOUT": 20000,
    "CONTENT_WAIT_TIMEOUT": 2000,
    "PRIORITY_URL_PATTERNS": [
        r"^/$", r"/about", r"/contact", r"/shop", r"/store", r"/products?",
        r"/services?", r"/pricing", r"/plans", r"/faq"
    ],
    "SKIP_URL_PATTERNS": [
        r"/blog/[^/]+$", r"/news/[^/]+$", r"/article", r"/post", r"/terms",
        r"/privacy", r"/cookies?", r"/legal", r"/policy", r"/login", r"/signup",
        r"/register", r"/cart", r"/checkout", r"/account"
    ],
    "REQUIRED_FIELDS": [
        "business_name", "short_description",
        "payment_information.payment_methods", "payment_information.payment_plans",
    ],
    "MIN_PRODUCTS": 2,
    "MIN_SERVICES": 1,
    "MIN_FAQS": 3,
    "DISABLE_EARLY_TERMINATION": True
}

# --- Load Configuration from File --- 
def load_scraper_config(config_path="scraper_config.json") -> Dict[str, Any]:
    """Loads configuration from a JSON file, falling back to defaults."""
    loaded_config = {}
    try:
        # Determine path relative to this script file
        script_dir = os.path.dirname(__file__)
        abs_config_path = os.path.join(script_dir, config_path)
        if os.path.exists(abs_config_path):
            with open(abs_config_path, 'r', encoding='utf-8') as f:
                loaded_config = json.load(f)
            logger.info(f"Loaded configuration from {abs_config_path}")
        else:
            logger.warning(f"Configuration file not found at {abs_config_path}. Using default settings.")
    except json.JSONDecodeError as e:
        logger.error(f"Error decoding JSON from {config_path}: {e}. Using default settings.")
        loaded_config = {}
    except Exception as e:
        logger.error(f"Error loading configuration file {config_path}: {e}. Using default settings.")
        loaded_config = {}
        
    # Merge loaded config with defaults (defaults are overridden by loaded values)
    final_config = default_config.copy()
    final_config.update(loaded_config)
    return final_config

# Load config when script starts
config = load_scraper_config()

# --- Helper Functions using Config --- 
def should_process_url(url: str) -> bool:
    """Determine if a URL should be processed based on priority and skip patterns."""
    path = urlparse(url).path
    
    # Use config values
    skip_patterns = config.get("SKIP_URL_PATTERNS", [])
    priority_patterns = config.get("PRIORITY_URL_PATTERNS", [])
    
    for pattern in skip_patterns:
        if re.search(pattern, path):
            logger.debug(f"Skipping URL (matched skip pattern): {url}")
            return False
    
    if not priority_patterns:
        return True
        
    if path == "/" or not path:
        return True
        
    for pattern in priority_patterns:
        if re.search(pattern, path):
            logger.debug(f"Processing URL (matched priority pattern): {url}")
            return True
            
    logger.debug(f"Deprioritizing URL (no priority match): {url}")
    return False

def is_sufficient_data(profile: Dict[str, Any]) -> bool:
    """Determine if we have collected sufficient data to stop scraping early."""
    # Use config values
    if config.get("DISABLE_EARLY_TERMINATION", True):
        return False
        
    if len(profile.get("source_urls", [])) < 5: 
        return False
    
    if not profile.get("business_name") or not profile.get("description"):
        return False

    if len(profile.get("offerings", [])) < config.get("MIN_PRODUCTS", 2) + config.get("MIN_SERVICES", 1): # Simplified check
        return False
        
    offerings_with_pricing = sum(1 for offering in profile.get("offerings", []) if offering.get("pricing"))
    if offerings_with_pricing < len(profile.get("offerings", [])) / 2:
        return False
    
    payment_options = profile.get("payment_options", {})
    if (not payment_options.get("methods") or len(payment_options.get("methods", [])) < 2 or
        not payment_options.get("plans") or len(payment_options.get("plans", [])) < 2):
        return False
    
    if len(profile.get("faqs", [])) < config.get("MIN_FAQS", 3):
        return False
    
    if (not profile.get("value_props") or len(profile.get("value_props", [])) < 3 or
        not profile.get("audience") or len(profile.get("audience", [])) < 3):
        return False
    
    contact_info = profile.get("contact_info", {})
    if not contact_info.get("email") and not contact_info.get("phone"):
        return False
    
    if not profile.get("social_links") or len(profile.get("social_links", {})) < 2:
        return False
    
    logger.info("Sufficient data collected to stop scraping early!")
    return True

def get_page_similarity(text1: str, text2: str) -> float:
    """Calculate similarity between two text contents (basic implementation)."""
    # Simple approach: create sets of words and calculate Jaccard similarity
    # More advanced approaches could use TF-IDF or embeddings
    if not text1 or not text2:
        return 0.0
    
    words1 = set(re.findall(r'\b\w+\b', text1.lower()))
    words2 = set(re.findall(r'\b\w+\b', text2.lower()))
    
    if not words1 or not words2:
        return 0.0
    
    # Jaccard similarity: intersection / union
    intersection = len(words1.intersection(words2))
    union = len(words1.union(words2))
    
    return intersection / union if union > 0 else 0.0

# Add the missing block_requests function
async def block_requests(route: Route, request: Request):
    """Block unnecessary resource types to speed up scraping."""
    BLOCKED_RESOURCE_TYPES = [
        'image',
        'media',
        'font',
        'stylesheet',
        'script',
        'texttrack',
        'xhr',
        'fetch',
        'eventsource',
        'websocket',
        'manifest',
        'other'
    ]
    
    if request.resource_type in BLOCKED_RESOURCE_TYPES:
        await route.abort()
    else:
        await route.continue_()

class Scraper:
    def __init__(self):
        # --- LLM Configuration ---
        self.llm = None
        llm_mode = os.getenv("LLM_MODE", "google").lower()  # Default to google if not set
        logger.info(f"Configured LLM Mode: {llm_mode}")

        if llm_mode == "google":
            google_api_key = os.getenv("GOOGLE_API_KEY")
            if google_api_key:
                self.llm = ChatGoogleGenerativeAI(
                    model="gemini-1.5-flash-latest",  # Or "gemini-pro"
                    google_api_key=google_api_key,
                    temperature=0.1,
                    convert_system_message_to_human=True
                )
                logger.info("Using Google Gemini LLM.")
            else:
                logger.warning("LLM_MODE set to 'google' but GOOGLE_API_KEY is not found in .env.")

        elif llm_mode == "deepseek":
            deepseek_api_key = os.getenv("DEEPSEEK_API_KEY")
            if deepseek_api_key:
                 self.llm = ChatDeepSeek(
                     temperature=0.1,
                     model="deepseek-chat",
                     api_key=deepseek_api_key,
                     api_base=os.getenv("DEEPSEEK_API_BASE"),
                 )
                 logger.info("Using DeepSeek LLM.")
            else:
                 logger.warning("LLM_MODE set to 'deepseek' but DEEPSEEK_API_KEY is not found in .env.")
        else:
             logger.warning(f"Invalid LLM_MODE specified: '{llm_mode}'. Please use 'google' or 'deepseek'. Falling back.")
             # Optional: Fallback logic or try default (e.g., google if key exists)
             google_api_key = os.getenv("GOOGLE_API_KEY")
             if google_api_key:
                 self.llm = ChatGoogleGenerativeAI(model="gemini-1.5-flash-latest", google_api_key=google_api_key, temperature=0.1, convert_system_message_to_human=True)
                 logger.info("Falling back to Google Gemini LLM as default.")
             else:  # Add a check for deepseek as a final fallback if google isn't available
                 deepseek_api_key = os.getenv("DEEPSEEK_API_KEY")
                 if deepseek_api_key:
                     self.llm = ChatDeepSeek(temperature=0.1, model="deepseek-chat", api_key=deepseek_api_key, api_base=os.getenv("DEEPSEEK_API_BASE"))
                     logger.info("Falling back to Deepseek LLM as default.")

        if not self.llm:
            raise ValueError(f"LLM could not be configured. Check LLM_MODE ('{llm_mode}') and ensure the corresponding API key (GOOGLE_API_KEY or DEEPSEEK_API_KEY) is set in your .env file.")

        self.playwright = None
        self.browser = None
        self.base_domain = ""
        self.social_links = {}
        self.scraped_urls = set()
        self.internal_links = set()
        self.page_results = []
        self.max_pages = config.get("MAX_INTERNAL_PAGES", 15)
        self.page_contents = {}
        self.early_termination = False
        self.priority_queue = []
        self.config = config

    async def setup(self):
        if self.playwright and self.browser: return
        try:
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(headless=True)
            logger.info("Playwright setup complete.")
        except Exception as e:
            logger.error(f"Error during Playwright setup: {str(e)}")
            raise

    async def cleanup(self):
        try:
            if self.browser: 
                await self.browser.close()
                self.browser = None
            if self.playwright: 
                await self.playwright.stop()
                self.playwright = None
            logger.info("Playwright cleanup complete.")
        except Exception as e:
            logger.error(f"Error during cleanup: {str(e)}")

    async def _extract_focused_content(self, page: Page) -> str:
        """Try to extract text from main content areas first."""
        text_content = ""
        for selector in self.config.get("TARGET_CONTENT_SELECTORS", ["body"]):
            try:
                # Use inner_text which is often better for user-visible text
                locator = page.locator(selector)
                count = await locator.count()
                if count > 0:
                     # If multiple elements match (e.g., multiple <article>), concatenate their text
                     all_texts = await locator.all_inner_texts()
                     text_content = "\n\n".join(all_texts)
                     if text_content.strip():
                         logger.debug(f"Extracted content using selector: '{selector}'")
                         return text_content.strip()
            except PlaywrightError as e:
                logger.warning(f"Playwright error finding selector '{selector}': {e}")
            except Exception as e:
                 logger.warning(f"Error extracting text with selector '{selector}': {e}")

        # Fallback if no specific selectors worked (should always hit 'body')
        if not text_content.strip():
             logger.warning("No targeted content found, falling back to full body text (might be less accurate).")
             try:
                # Get text from body, excluding more noise tags
                text_content = await page.evaluate("""() => {
                    const body = document.body.cloneNode(true);
                    // More aggressive noise removal
                    body.querySelectorAll('script, style, nav, footer, header, noscript, svg, button, input, select, textarea, aside, iframe, [role="banner"], [role="navigation"], .nav, .footer, .sidebar, .menu, .comments, #comments, .ad, .ads, #sidebar').forEach(el => el.remove());
                    return body.innerText;
                 }""")
             except Exception as e:
                  logger.error(f"Failed to extract fallback body text: {e}")
                  return ""  # Return empty string if even fallback fails

        return text_content.strip()

    async def _extract_social_links(self, page: Page, current_url: str) -> Dict[str, str]:
        """Extract social media links from a page."""
        social_domains = {
            "linkedin.com": "linkedin", "twitter.com": "twitter", "x.com": "twitter",
            "facebook.com": "facebook", "instagram.com": "instagram", "youtube.com": "youtube"
        }
        # Precise locators for common social link patterns
        targeted_social_locators = {
            'linkedin': 'a[href*="linkedin.com/company/"], a[href*="linkedin.com/in/"]',
            'twitter': 'a[href*="twitter.com/"], a[href*="x.com/"]',  # Check both
            'facebook': 'a[href*="facebook.com/"]',
            'instagram': 'a[href*="instagram.com/"]',
            'youtube': 'a[href*="youtube.com/channel/"], a[href*="youtube.com/user/"], a[href*="youtube.com/@"]'
        }
        social_links = {}

        # Extract social links using locators
        for site, locator in targeted_social_locators.items():
            try:
                elements = await page.locator(locator).all()
                if elements:
                    href = await elements[0].get_attribute('href')
                    if href:
                        abs_href = urljoin(current_url, href)
                        parsed_social = urlparse(abs_href)
                        if parsed_social.scheme in ['http', 'https'] and parsed_social.netloc:
                            if site not in social_links:  # Store first found
                                social_links[site] = abs_href
                                logger.debug(f"Found {site} link: {abs_href}")
            except Exception as e:
                logger.warning(f"Error during social link extraction for {site}: {e}")

        return social_links

    async def _extract_internal_links(self, page: Page, current_url: str) -> Set[str]:
        """Extract internal links from headers, footers, and main navigation."""
        internal_links = set()
        base_url = f"{urlparse(current_url).scheme}://{urlparse(current_url).netloc}"
        
        # First, extract links from navigation elements
        for selector in self.config.get("NAVIGATION_SELECTORS", []):
            try:
                # Get all anchor elements in the navigation
                locator = page.locator(f"{selector} a")
                count = await locator.count()
                if count > 0:
                    for i in range(count):
                        try:
                            href = await locator.nth(i).get_attribute('href')
                            if href and not href.startswith(('#', 'javascript:', 'mailto:', 'tel:', 'sms:', 'whatsapp:')):
                                abs_url = urljoin(current_url, href)
                                # Only include internal links (same domain)
                                parsed_url = urlparse(abs_url)
                                if parsed_url.netloc == urlparse(base_url).netloc and parsed_url.scheme in ['http', 'https']:
                                    # Remove hash fragments and normalize
                                    normalized_url = abs_url.split('#')[0].rstrip('/')
                                    internal_links.add(normalized_url)
                        except Exception as e:
                            logger.warning(f"Error processing link {i} in {selector}: {e}")
            except Exception as e:
                logger.warning(f"Error extracting links from {selector}: {e}")
        
        # Additionally, look specifically for course/product links which might be in cards or grids
        course_card_selectors = [
            ".course-card a", ".product-card a", ".service-card a", 
            ".card a", ".grid-item a", ".course-item a", ".program-card a",
            "[class*='course'] a", "[class*='bootcamp'] a"
        ]
        
        for selector in course_card_selectors:
            try:
                locator = page.locator(selector)
                count = await locator.count()
                if count > 0:
                    for i in range(count):
                        try:
                            href = await locator.nth(i).get_attribute('href')
                            if href and not href.startswith(('#', 'javascript:', 'mailto:', 'tel:', 'sms:', 'whatsapp:')):
                                abs_url = urljoin(current_url, href)
                                # Only include internal links (same domain)
                                parsed_url = urlparse(abs_url)
                                if parsed_url.netloc == urlparse(base_url).netloc and parsed_url.scheme in ['http', 'https']:
                                    # Remove hash fragments and normalize
                                    normalized_url = abs_url.split('#')[0].rstrip('/')
                                    internal_links.add(normalized_url)
                                    # These are high-priority links, log them specially
                                    logger.info(f"Found potential course/product link: {normalized_url}")
                        except Exception as e:
                            pass
            except Exception as e:
                pass
        
        # Also extract links from main content but only if we haven't found many from navigation
        if len(internal_links) < 5:
            try:
                # Extract links from main content areas
                for selector in self.config.get("TARGET_CONTENT_SELECTORS", []):
                    try:
                        locator = page.locator(f"{selector} a")
                        count = await locator.count()
                        if count > 0:
                            for i in range(count):
                                try:
                                    href = await locator.nth(i).get_attribute('href')
                                    if href and not href.startswith(('#', 'javascript:', 'mailto:', 'tel:', 'sms:', 'whatsapp:')):
                                        abs_url = urljoin(current_url, href)
                                        # Only include internal links (same domain)
                                        parsed_url = urlparse(abs_url)
                                        if parsed_url.netloc == urlparse(base_url).netloc and parsed_url.scheme in ['http', 'https']:
                                            # Remove hash fragments and normalize
                                            normalized_url = abs_url.split('#')[0].rstrip('/')
                                            internal_links.add(normalized_url)
                                except Exception as e:
                                    pass  # Skip individual link errors in content
                    except Exception as e:
                        # Continue to next selector if one fails
                        pass
            except Exception as e:
                logger.warning(f"Error extracting content links: {e}")

        # Filter URLs based on priority and skip patterns
        filtered_links = {url for url in internal_links if should_process_url(url)}
        
        # Sort internal links by priority for better iteration order later
        priority_patterns = self.config.get("PRIORITY_URL_PATTERNS", [])
        sorted_links = sorted(filtered_links, 
                             key=lambda url: 0 if any(re.search(pattern, urlparse(url).path) for pattern in priority_patterns) else 1)
        
        # Log the found links
        logger.info(f"Found {len(sorted_links)} relevant internal links (filtered from {len(internal_links)} total) on {current_url}")
        return set(sorted_links)

    async def _extract_pricing_elements(self, page: Page) -> Dict[str, str]:
        """Extract pricing information from the page using direct DOM queries."""
        pricing_info = {}
        
        # Define currency symbols and patterns we look for
        currencies = ['R', '$', '€', '£'] # ZAR, USD, EUR, GBP
        currency_symbols_escaped = '|'.join(re.escape(c) for c in currencies)
        # Corrected regex for has-text selector (currency symbol, optional space, digit)
        currency_pattern_text_selector = rf"/:has-text(/(?:{currency_symbols_escaped})\s?\d/)"
        # Corrected Python regex to extract the full price string (symbol + number)
        currency_pattern_regex = rf'({currency_symbols_escaped})\s?(\d{{1,3}}(?:[,.]\d{{3}})*(?:[,.]\d{{2}})?|\d+)'

        # Common price selectors - including direct text search for currency patterns
        price_selectors = [
            # Specific selectors (keep high priority)
            ".paymentPlans_cardPrice__PjEDy span",  
            ".paymentPlans_discounted_price__DwlIC",
            # Text-based selector looking for currency patterns
            currency_pattern_text_selector, # Look in any element
            # Class/ID based selectors (might find containers)
            "[class*='price']", 
            "[class*='pricing']",
            "[class*='cost']",   
            "[class*='fee']",    
            "[class*='payment']",
            "[class*='plan']",   
            "[id*='price']",    
            "[id*='pricing']",  
            ".price",
            ".pricing",
            ".cost",
            ".fee",
            ".plan-price",
            ".amount", 
            ".price-value", 
            ".product-price", 
        ]
        
        # Try each selector
        for selector in price_selectors:
            try:
                elements = page.locator(selector)
                count = await elements.count()
                if count > 0:
                    for i in range(count):
                        try:
                            element = elements.nth(i)
                            # Check visibility to avoid hidden elements
                            if not await element.is_visible():
                               continue 
                               
                            text = await element.text_content()
                            # Clean text to remove whitespace and potential prefixes/suffixes
                            cleaned_text = text.strip() if text else ""
                            
                            # More robust check for price-like patterns using the updated regex
                            # Use re.finditer to catch multiple prices in one element if needed
                            for price_match in re.finditer(currency_pattern_regex, cleaned_text):
                                # Combine symbol and number group to get the full price string
                                extracted_price = price_match.group(1) + price_match.group(2) 
                                
                                # Get the course name from URL or page
                                url_path = urlparse(page.url).path
                                course_name = "Unknown"
                                
                                # Try to determine course type from URL
                                if "datascience" in url_path or "data-science" in url_path:
                                    course_name = "Data Science Bootcamp"
                                elif "fullstack" in url_path or "web-development" in url_path:
                                    course_name = "Fullstack Web Development Bootcamp"
                                elif "cyber" in url_path:
                                    course_name = "Cybersecurity Bootcamp"
                                else:
                                    # Try to find course name in page (limited search for efficiency)
                                    heading_selectors = ["h1", "h2", ".course-title", ".product-title"]
                                    parent = element
                                    # Look for headings near the price element (up to 3 levels up)
                                    for _ in range(3):
                                        found_name = False
                                        for h_selector in heading_selectors:
                                            try:
                                                heading = parent.locator(f"xpath=ancestor-or-self::*/*[{h_selector}]").first
                                                if await heading.count() > 0:
                                                   heading_text = await heading.text_content()
                                                   if heading_text:
                                                      course_name = heading_text.strip()
                                                      found_name = True
                                                      break # Found heading
                                            except: pass # Ignore errors finding headings
                                        if found_name: break # Stop searching ancestors if name found
                                        try:
                                            parent = parent.locator('xpath=..') # Move up one level
                                            if await parent.count() == 0: break # Stop if no parent
                                        except: break # Stop if error moving up
                                
                                # Store the price with course name, only if not already found or if this is more specific
                                if course_name not in pricing_info or len(extracted_price) > len(pricing_info.get(course_name, "")):
                                    pricing_info[course_name] = extracted_price
                                    logger.info(f"Found pricing: {extracted_price} for {course_name} using selector: {selector}")
                        except Exception as e:
                            logger.debug(f"Error extracting price from element {i} for selector '{selector}': {e}")
            except Exception as e:
                # Log errors specifically related to has-text or invalid selectors
                if ":has-text" in selector or "Unknown engine" in str(e):
                     logger.warning(f"Possible invalid selector '{selector}': {e}")
                else:
                    logger.debug(f"Error with general price selector '{selector}': {e}")
        
        return pricing_info

    async def analyze_page_content_for_sales(self, content: str, url: str) -> Dict[str, Any]:
        """Analyze page content using LLM with a simplified schema for faster results."""
        content_to_analyze = content[:self.config.get("MAX_CONTENT_LENGTH", 10000)]
        if len(content) > self.config.get("MAX_CONTENT_LENGTH", 10000):
            logger.debug(f"Truncating content for LLM analysis from {len(content)} to {self.config.get('MAX_CONTENT_LENGTH', 10000)} chars for {url}")

        # --- Generalized Prompt --- #
        prompt = f"""
        Analyze the text content from webpage '{url}' and extract essential business information.
        Return ONLY a JSON object with these fields:

        {{
            "business_name": "Primary business name mentioned (string or null)",
            "tagline_slogan": "Company tagline or slogan if explicitly stated (string or null)",
            "short_description": "A brief (1-2 sentence) description of the company or its main offering (string or null)",
            "offerings": [
                {{
                    "type": "product, service, subscription, etc. (string)",
                    "name": "Name of the offering (string)",
                    "description": "Description of what it is (string or null)",
                    "attributes": ["Key features, benefits, or specifications (list of strings)"],
                    "pricing": "Specific pricing information including cost, payment terms, financing options if available (string or null)"
                }}
            ],
            "payment_information": {{
                "payment_methods": ["List of payment methods accepted (credit cards, PayPal, bank transfer, etc.)"],
                "payment_plans": ["List of payment plans offered (monthly, annual, one-time, subscription levels, etc.)"],
                "pricing_tiers": ["List of pricing tiers or packages mentioned (Basic, Pro, Enterprise, etc.)"],
                "free_offers": "Details about any free trials, demos, samples, or consultations offered (string or null)"
            }},
            "value_propositions": ["List key unique selling points or value propositions (list of strings)"],
            "target_audience": ["List target customer groups or market segments (list of strings)"],
            "support_channels": ["List available customer support channels mentioned (email, phone, chat, helpdesk, etc.)"],
            "contact_info": {{
                "email": "Contact email address(es) (string or null)",
                "phone": "Contact phone number(s) (string or null)",
                "address": "Physical address(es) if mentioned (string or null)",
                "contact_form_mention": "Is a contact form mentioned? (boolean or null)"
            }},
            "faqs": [
                {{
                    "question": "The question text (string)",
                    "answer": "The answer text (string)"
                }}
            ],
            "page_topic": "Main topic of this specific page (e.g. Homepage, About Us, Product Page - [Product Name], Service Page - [Service Name], Contact, Pricing, FAQ) (string)",
            "extracted_from_url": "{url}"
        }}

        Be extremely concise. Only return JSON - no explanations, markdown, or extra text.

        IMPORTANT INSTRUCTIONS:
        1.  **Offerings & Pricing:** When describing items in the 'offerings' array, pay VERY close attention to extracting any specific pricing details mentioned nearby (cost, payment terms, currency). Include this in the 'pricing' field for that offering.
        2.  **Contact Details:** Thoroughly extract any contact information (email, phone, address) found anywhere on the page and place it in the 'contact_info' fields.
        3.  **General Payment Info:** Capture general payment methods or plans mentioned outside specific offerings in the 'payment_information' section.
        4.  **Conciseness:** Keep descriptions brief and focused.

        Content from webpage:
        {content_to_analyze}
        """

        try:
            logger.debug(f"Invoking LLM for page analysis: {url}")
            response = await self.llm.ainvoke(prompt)
            if not response or not response.content:
                logger.warning(f"LLM returned no content for {url}")
                return {"error": "No response content from LLM", "extracted_from_url": url, "page_topic": "Unknown"}

            result = extract_json_from_markdown(response.content)

            # Ensure extracted_from_url is present, even if LLM misses it
            if "error" not in result and "extracted_from_url" not in result:
                result["extracted_from_url"] = url
            # Ensure page_topic has a default if missing
            if "page_topic" not in result: 
                result["page_topic"] = "Unknown"

            if "error" in result:
                logger.error(f"LLM analysis failed for {url}. Error: {result.get('error')}")
                # Add defaults to error structure for consistency
                result["extracted_from_url"] = url
                if "page_topic" not in result: 
                    result["page_topic"] = "Unknown"
                return result

            # Validate list fields
            list_fields = [
                "offerings", "value_propositions", "target_audience", 
                "support_channels", "faqs"
            ]
            for list_field in list_fields:
                if list_field in result and not isinstance(result[list_field], list):
                    if result[list_field] is not None: 
                        result[list_field] = [result[list_field]]
                    else: 
                        result[list_field] = []
            
            # Handle backward compatibility with old product/service format
            if ("products" in result or "services" in result) and "offerings" not in result:
                result["offerings"] = []
                
                # Convert products to offerings
                if "products" in result and isinstance(result["products"], list):
                    for product in result["products"]:
                        if product.get("name"):
                            offering = {
                                "type": "product",
                                "name": product["name"],
                                "description": product.get("description"),
                                "attributes": product.get("features", []),
                                "pricing": None
                            }
                            result["offerings"].append(offering)
                
                # Convert services to offerings
                if "services" in result and isinstance(result["services"], list):
                    for service in result["services"]:
                        if service.get("name"):
                            offering = {
                                "type": "service",
                                "name": service["name"],
                                "description": service.get("scope"),
                                "attributes": service.get("benefits", []),
                                "pricing": None
                            }
                            result["offerings"].append(offering)
                        
            # Ensure payment_information object exists
            if "payment_information" not in result:
                result["payment_information"] = {
                    "payment_methods": [],
                    "payment_plans": [],
                    "pricing_tiers": [],
                    "free_offers": None
                }
            # Validate payment information lists
            payment_list_fields = ["payment_methods", "payment_plans", "pricing_tiers"]
            for field in payment_list_fields:
                if field in result.get("payment_information", {}) and not isinstance(result["payment_information"][field], list):
                    if result["payment_information"][field] is not None:
                        result["payment_information"][field] = [result["payment_information"][field]]
                    else:
                        result["payment_information"][field] = []

            return result

        except Exception as e:
            error_msg = f"Error during LLM analysis for {url}: {str(e)}"
            logger.exception(error_msg)
            return {"error": error_msg, "extracted_from_url": url, "page_topic": "Unknown"}

    async def process_page(self, url: str) -> Dict[str, Any]:
        """Process a single page and return its analysis."""
        if url in self.scraped_urls:
            logger.info(f"Skipping already scraped URL: {url}")
            return None
            
        self.scraped_urls.add(url)
        logger.info(f"Processing page: {url}")
        
        try:
            context = await self.browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            )
            
            page = await context.new_page()
            
            if self.config.get("BLOCK_RESOURCES", True):
                await page.route("**/*", block_requests)
                
            try:
                # Use config values for timeouts
                page_load_timeout = self.config.get("PAGE_LOAD_TIMEOUT", 20000)
                content_wait_timeout = self.config.get("CONTENT_WAIT_TIMEOUT", 2000)
                
                response = await page.goto(
                    url, 
                    wait_until="domcontentloaded", 
                    timeout=page_load_timeout
                )
                
                if not response or not response.ok:
                    logger.warning(f"Failed to load {url}: Status {response.status if response else 'N/A'}")
                    return {"error": f"Failed to load page: Status {response.status if response else 'N/A'}", "url": url}
                    
                current_url = page.url
                
                # Brief wait for dynamic content if needed (but keep it short)
                try:
                    await asyncio.wait_for(page.wait_for_load_state("networkidle"), content_wait_timeout/1000)
                except (asyncio.TimeoutError, PlaywrightError):
                    # Continue anyway if timeout - we already have the main content
                    pass
                
                # Extract internal links if we haven't reached the maximum and it's the first few pages
                if len(self.scraped_urls) <= 3:  # Only extract from first 3 pages to save time
                    new_internal_links = await self._extract_internal_links(page, current_url)
                    self.internal_links.update(new_internal_links)
                    
                    # Sort internal links by priority
                    self.priority_queue = sorted(
                        self.internal_links - self.scraped_urls,
                        key=lambda url: 0 if any(re.search(pattern, urlparse(url).path) for pattern in self.config.get("PRIORITY_URL_PATTERNS", [])) else 1
                    )
                
                # Extract the main content
                text_content = await self._extract_focused_content(page)
                
                if not text_content:
                    logger.warning(f"No text content extracted from {current_url}")
                    return {"error": "No text content found on page", "url": current_url}
                
                # Check for duplicate/similar content
                for existing_url, existing_content in self.page_contents.items():
                    similarity = get_page_similarity(text_content, existing_content)
                    if similarity > 0.7:  # Threshold for considering pages similar
                        logger.info(f"Skipping page with similar content to {existing_url} (similarity: {similarity:.2f})")
                        return {
                            "error": f"Similar content to already processed page: {existing_url}",
                            "url": current_url,
                            "similarity": similarity
                        }
                
                # Store content for future similarity checks
                self.page_contents[current_url] = text_content
                
                # Extract social media links
                social_links = await self._extract_social_links(page, current_url)
                # Merge with existing social links
                for platform, link in social_links.items():
                    if platform not in self.social_links:
                        self.social_links[platform] = link
                
                # NEW: Extract pricing information directly from DOM
                pricing_info = await self._extract_pricing_elements(page)
                
                # Analyze content with LLM
                analysis_result = await self.analyze_page_content_for_sales(text_content, current_url)
                # Ensure URL is included in the result
                analysis_result["_url"] = current_url
                
                # Add pricing information to the analysis result
                if pricing_info:
                    # Create a special field for direct pricing info
                    analysis_result["_direct_pricing"] = pricing_info
                    
                    # Update any matching offerings with the specific pricing
                    if analysis_result.get("offerings") and isinstance(analysis_result["offerings"], list):
                        for offering in analysis_result["offerings"]:
                            if offering.get("name"):
                                # Try to match offering name with pricing info
                                for course_name, price in pricing_info.items():
                                    if course_name.lower() in offering["name"].lower() or offering["name"].lower() in course_name.lower():
                                        offering["pricing"] = price
                                        logger.info(f"Updated pricing for {offering['name']} to {price}")
                
                # Check if we have sufficient data after adding this result to terminate early
                if not self.early_termination:
                    temp_results = self.page_results + [analysis_result]
                    temp_profile = self._compile_flexible_business_profile(temp_results)
                    if is_sufficient_data(temp_profile):
                        logger.info("Found sufficient data to terminate scraping early")
                        self.early_termination = True
                
                return analysis_result
                
            except Exception as e:
                logger.exception(f"Error processing page {url}: {str(e)}")
                return {"error": f"Error processing page: {str(e)}", "url": url}
                
            finally:
                await page.close()
                await context.close()
                
        except Exception as e:
            logger.exception(f"Error setting up browser for {url}: {str(e)}")
            return {"error": f"Browser setup error: {str(e)}", "url": url}

    def _compile_flexible_business_profile(self, results=None) -> Dict[str, Any]:
        """Create a more flexible business profile that adapts to different business types."""
        # If results not provided, use self.page_results
        if results is None:
            results = self.page_results
            
        if not results:
            return {"error": "No pages were successfully analyzed"}
        
        # Start with the first page as base (usually homepage)
        homepage_result = next((page for page in results 
                               if "error" not in page and 
                               page.get("page_topic", "").lower() in ["homepage", "home", "main", "landing"]), 
                              results[0])
        
        # Initialize with core fields every business should have
        profile = {
            "business_name": homepage_result.get("business_name"),
            "tagline": homepage_result.get("tagline_slogan"),
            "description": homepage_result.get("short_description"),
            "contact_info": homepage_result.get("contact_info", {}),
            "offerings": [],  # Flexible container for products, services, or other offerings
            "value_props": [],  # Value propositions / USPs
            "audience": [],  # Target audience segments
            "payment_options": {
                "methods": [],  # How customers can pay
                "plans": [],    # Payment structures
                "tiers": [],    # Different pricing levels
                "free_offer": None  # Free trial or similar offer
            },
            "support": [],  # Support channels
            "faqs": [],  # Frequently asked questions
            "social_links": {},  # Social media profiles
            "source_urls": [],  # Pages scraped
            "base_domain": self.base_domain,
            "business_type": None,  # Will be inferred
            "course_prices": {}  # NEW: Store specific course prices
        }
        
        # Track what we've already added to avoid duplicates
        seen_offerings = {}  # Change to dict to track by name for merging
        seen_value_props = set()
        seen_audience = set()
        seen_payment_methods = set()
        seen_payment_plans = set()
        seen_payment_tiers = set()
        seen_support = set()
        seen_faqs = set()
        
        # Collect direct pricing information from all pages
        direct_pricing = {}
        for page_result in results:
            if "_direct_pricing" in page_result and isinstance(page_result["_direct_pricing"], dict):
                direct_pricing.update(page_result["_direct_pricing"])
        
        # Process each page result to build the profile
        for page_result in results:
            if "error" in page_result:
                continue
                
            # Add source URL to keep track of where data came from
            if "_url" in page_result:
                profile["source_urls"].append(page_result["_url"])
            
            # Process basic information (only take if not already set)
            if not profile["business_name"] and page_result.get("business_name"):
                profile["business_name"] = page_result["business_name"]
                
            if not profile["tagline"] and page_result.get("tagline_slogan"):
                profile["tagline"] = page_result["tagline_slogan"]
                
            if not profile["description"] and page_result.get("short_description"):
                profile["description"] = page_result["short_description"]
            
            # Process contact info - combine all found info
            if page_result.get("contact_info") and isinstance(page_result["contact_info"], dict):
                for key, value in page_result["contact_info"].items():
                    if value and (key not in profile["contact_info"] or not profile["contact_info"][key]):
                        profile["contact_info"][key] = value
            
            # Handle old format contact info
            if page_result.get("sales_contact_info") and isinstance(page_result["sales_contact_info"], dict):
                for key, value in page_result["sales_contact_info"].items():
                    if value and (key not in profile["contact_info"] or not profile["contact_info"][key]):
                        profile["contact_info"][key] = value
            
            # Process offerings (new format) - merge with existing if same name
            if page_result.get("offerings") and isinstance(page_result["offerings"], list):
                for offering in page_result["offerings"]:
                    if not offering.get("name"):
                        continue
                        
                    offering_name = offering["name"].lower()
                    # Check if we've seen this offering before
                    if offering_name in seen_offerings:
                        # Merge with existing offering
                        existing_idx = seen_offerings[offering_name]
                        existing = profile["offerings"][existing_idx]
                        
                        # Take the most detailed description
                        if offering.get("description") and (not existing.get("description") or 
                                                           len(str(offering["description"])) > len(str(existing["description"]))):
                            existing["description"] = offering["description"]
                        
                        # Add new attributes
                        if offering.get("attributes"):
                            existing_attrs = {attr.lower() for attr in existing.get("attributes", [])}
                            for attr in offering.get("attributes", []):
                                if attr and attr.lower() not in existing_attrs:
                                    existing["attributes"].append(attr)
                                    existing_attrs.add(attr.lower())
                        
                        # Take pricing if available
                        if offering.get("pricing") and not existing.get("pricing"):
                            existing["pricing"] = offering["pricing"]
                    else:
                        # Add as new offering
                        profile["offerings"].append(offering)
                        seen_offerings[offering_name] = len(profile["offerings"]) - 1
            
            # Process FAQs
            if page_result.get("faqs") and isinstance(page_result["faqs"], list):
                for faq in page_result["faqs"]:
                    if faq.get("question") and faq["question"].lower() not in seen_faqs:
                        profile["faqs"].append(faq)
                        seen_faqs.add(faq["question"].lower())
            
            # Process payment information
            if page_result.get("payment_information") and isinstance(page_result["payment_information"], dict):
                payment_info = page_result["payment_information"]
                
                # Payment methods
                for method in payment_info.get("payment_methods", []):
                    if method and method.lower() not in seen_payment_methods:
                        profile["payment_options"]["methods"].append(method)
                        seen_payment_methods.add(method.lower())
                
                # Payment plans
                for plan in payment_info.get("payment_plans", []):
                    if plan and plan.lower() not in seen_payment_plans:
                        profile["payment_options"]["plans"].append(plan)
                        seen_payment_plans.add(plan.lower())
                
                # Pricing tiers
                for tier in payment_info.get("pricing_tiers", []):
                    if tier and tier.lower() not in seen_payment_tiers:
                        profile["payment_options"]["tiers"].append(tier)
                        seen_payment_tiers.add(tier.lower())
                
                # Free offers/trials
                free_offer = payment_info.get("free_offers") or payment_info.get("free_trials")
                if free_offer and (not profile["payment_options"]["free_offer"] or 
                                 len(str(free_offer)) > len(str(profile["payment_options"]["free_offer"] or ""))):
                    profile["payment_options"]["free_offer"] = free_offer
            
            # Process value propositions (both new and old format)
            value_props_field = page_result.get("value_propositions", []) or page_result.get("unique_selling_proposition_usp", [])
            for prop in value_props_field:
                if prop and prop.lower() not in seen_value_props:
                    profile["value_props"].append(prop)
                    seen_value_props.add(prop.lower())
            
            # Process target audience (both new and old format)
            audience_field = page_result.get("target_audience", []) or page_result.get("customer_segments", [])
            for segment in audience_field:
                if segment and segment.lower() not in seen_audience:
                    profile["audience"].append(segment)
                    seen_audience.add(segment.lower())
            
            # Process support channels
            for channel in page_result.get("support_channels", []):
                if channel and channel.lower() not in seen_support:
                    profile["support"].append(channel)
                    seen_support.add(channel.lower())
        
        # Apply any direct pricing information we collected (more robust matching)
        if direct_pricing:
            profile["course_prices"] = direct_pricing # Store the raw directly extracted prices
            for offering in profile.get("offerings", []):
                if offering.get("name"):
                    offering_name_lower = offering["name"].lower()
                    best_match_price = offering.get("pricing") # Keep existing price if already set
                    
                    for course_key, price in direct_pricing.items():
                        course_key_lower = course_key.lower()
                        # Check for exact match, containment, or keyword overlap
                        if (offering_name_lower == course_key_lower or 
                            offering_name_lower in course_key_lower or 
                            course_key_lower in offering_name_lower or 
                            # Simple keyword check (e.g., 'datascience' vs 'data science bootcamp')
                            any(keyword in course_key_lower for keyword in offering_name_lower.split() if len(keyword) > 3) or
                            any(keyword in offering_name_lower for keyword in course_key_lower.split() if len(keyword) > 3) ):
                            
                            # Prioritize updating if current price is None or if this price seems more specific
                            if best_match_price is None or (price and len(str(price)) > len(str(best_match_price))):
                                best_match_price = price
                                logger.info(f"Applying direct pricing match: {price} to {offering['name']}")
                                
                    # Update the offering's price with the best match found
                    offering["pricing"] = best_match_price
        
        # Add social media links
        if self.social_links:
            profile["social_links"] = self.social_links
        
        # Infer business type from offerings
        if profile["offerings"]:
            product_count = sum(1 for o in profile["offerings"] if o.get("type") == "product")
            service_count = sum(1 for o in profile["offerings"] if o.get("type") == "service")
            
            if product_count > 0 and service_count == 0:
                profile["business_type"] = "product-based"
            elif service_count > 0 and product_count == 0:
                profile["business_type"] = "service-based"
            elif product_count > 0 and service_count > 0:
                profile["business_type"] = "hybrid"
            else:
                profile["business_type"] = "other"
        
        # Add fallback for business name if not found
        if not profile["business_name"] and self.base_domain:
            domain_parts = self.base_domain.split('.')
            profile["business_name"] = domain_parts[0].capitalize()
            
        # Logging for debugging
        logger.info(f"Compiled business profile with {len(profile['offerings'])} offerings, " +
                   f"{len(profile['value_props'])} value props, {len(profile['faqs'])} FAQs")
        
        return profile

    async def scrape(self, url: str, max_pages: Optional[int] = None) -> Dict[str, Any]:
        """Scrape a website starting from the URL, following internal links up to max_pages."""
        start_time = time.time()
        
        try:
            # Use max_pages override if provided, otherwise use config
            self.max_pages = max_pages if max_pages is not None else self.config.get("MAX_INTERNAL_PAGES", 15)
            
            # Reset state for new scrape
            self.scraped_urls = set()
            self.internal_links = set()
            self.page_results = []
            self.page_contents = {}
            self.early_termination = False
            self.priority_queue = []
            
            # Validate and normalize URL
            if not url.startswith(('http://', 'https://')):
                url = 'https://' + url  # Assume https if missing
                
            parsed_url = urlparse(url)
            self.base_domain = parsed_url.netloc.replace('www.', '')
            
            if not self.base_domain or '.' not in self.base_domain:
                raise ValueError(f"Invalid URL: {url}")
                
            logger.info(f"Starting scrape of: {url} (up to {self.max_pages} pages)")
            await self.setup()
            
            # Process the initial page
            initial_result = await self.process_page(url)
            if initial_result:
                self.page_results.append(initial_result)
            
            # Now process the internal links in parallel batches
            while (self.priority_queue or self.internal_links) and len(self.scraped_urls) < self.max_pages and not self.early_termination:
                # Get next batch of URLs to process
                if self.priority_queue:
                    urls_to_process = self.priority_queue[:self.max_pages - len(self.scraped_urls)]
                    self.priority_queue = self.priority_queue[len(urls_to_process):]
                else:
                    urls_to_process = list(self.internal_links - self.scraped_urls)[:self.max_pages - len(self.scraped_urls)]
                
                if not urls_to_process:
                    break
                
                logger.info(f"Processing batch of {len(urls_to_process)} pages")
                
                # Process in smaller batches to limit concurrency
                batch_size = min(self.config.get("MAX_CONCURRENT_SCRAPES", 5), len(urls_to_process))
                for i in range(0, len(urls_to_process), batch_size):
                    if self.early_termination:
                        logger.info("Early termination triggered - stopping batch processing")
                        break
                        
                    batch = urls_to_process[i:i + batch_size]
                    
                    # Process this batch concurrently
                    tasks = [self.process_page(url) for url in batch]
                    batch_results = await asyncio.gather(*tasks, return_exceptions=True)
                    
                    # Filter out exceptions and None results
                    valid_results = [r for r in batch_results if r is not None and not isinstance(r, Exception) and "error" not in r]
                    self.page_results.extend(valid_results)
                    
                    # Log errors
                    errors = [r for r in batch_results if isinstance(r, Exception)]
                    for e in errors:
                        logger.error(f"Batch processing error: {str(e)}")
                    
                    # Check for early termination
                    if self.early_termination:
                        logger.info("Early termination condition met - stopping batch processing")
                        break
            
            # Compile the final business profile using the new flexible approach
            business_profile = self._compile_flexible_business_profile()
            
            # Add metadata
            result = {
                "scrape_metadata": {
                    "url": url,
                    "base_domain": self.base_domain,
                    "pages_scraped": len(self.scraped_urls),
                    "pages_analyzed": len(self.page_results),
                    "early_termination": self.early_termination,
                    "scrape_time": datetime.now().isoformat(),
                    "processing_time_seconds": time.time() - start_time
                },
                "business_profile": business_profile
            }
            
            # Save results to file
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_base_domain = re.sub(r'[^\w\-.]', '_', self.base_domain)
            filename = f"multi_page_scrape_{safe_base_domain}_{timestamp}.json"
            filepath = os.path.join(RESULTS_DIR, filename)
            
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(result, f, indent=2, ensure_ascii=False)
            logger.info(f"Results saved to {filepath}")
            
            # Add filename to metadata
            result["scrape_metadata"]["filename"] = filename
            
            return result
            
        except Exception as e:
            logger.exception(f"Error during scrape: {str(e)}")
            return {"error": f"Scrape failed: {str(e)}"}
            
        finally:
            await self.cleanup()

# Helper function to run the scraper
async def scrape_website(url: str, max_pages: Optional[int] = None) -> Dict[str, Any]:
    """Helper function to create and run a scraper instance."""
    scraper = Scraper()
    try:
        # Pass max_pages override to the scrape method
        return await scraper.scrape(url, max_pages=max_pages)
    except Exception as e:
        logger.error(f"Error during scrape: {str(e)}")
        return {"error": f"Scrape failed: {str(e)}"}

# --- Main Execution Block ---
if __name__ == "__main__":
    import sys
    import argparse

    # Use the config default for max_pages in the argument parser
    default_max_pages = config.get("MAX_INTERNAL_PAGES", 15)
    parser = argparse.ArgumentParser(description="Web scraper for business profiles with multi-page support")
    parser.add_argument("url", help="URL to scrape")
    parser.add_argument("--max-pages", type=int, default=default_max_pages, 
                        help=f"Maximum number of internal pages to scrape (default: {default_max_pages})")
    
    if len(sys.argv) == 1:
        # Simple example if no args provided
        print("Usage: python -m src.crawler.scraper <url> [--max-pages N]")
        # Use config default for example
        example_max_pages = config.get("MAX_INTERNAL_PAGES", 10) # Reduced example default
        print(f"Running with default example: python -m src.crawler.scraper https://www.zaio.io/ --max-pages {example_max_pages}")
        example_url = "https://www.zaio.io/"
        # Pass the example limit
        results = asyncio.run(scrape_website(example_url, max_pages=example_max_pages)) 
    else:
        args = parser.parse_args()
        print(f"Starting scrape of URL: {args.url} (max pages: {args.max_pages})")
        # Pass the parsed max_pages argument
        results = asyncio.run(scrape_website(args.url, args.max_pages))

    # Print summary after scrape
    if results and "business_profile" in results and "error" not in results.get("business_profile", {}):
        print("\n--- Scrape Completed Successfully ---")
        print(f"URL: {results.get('scrape_metadata', {}).get('url', 'N/A')}")
        print(f"Pages Scraped: {results.get('scrape_metadata', {}).get('pages_scraped', 'N/A')}")
        print(f"Time: {results.get('scrape_metadata', {}).get('processing_time_seconds', 'N/A'):.2f} seconds")
        
        profile = results.get('business_profile', {})
        print("\n--- Business Profile (Summary) ---")
        print(f"Business Name: {profile.get('business_name', 'N/A')}")
        print(f"Tagline: {profile.get('tagline', 'N/A')}")
        print(f"Description: {profile.get('description', 'N/A')}")
        
        if profile.get('products'):
            print(f"Products Found: {len(profile.get('products', []))}")
        if profile.get('services'):
            print(f"Services Found: {len(profile.get('services', []))}")
        if profile.get('faqs'):
            print(f"FAQs Found: {len(profile.get('faqs', []))}")
        if profile.get('payment_options'):
            payment_info = profile.get('payment_options', {})
            print(f"Payment Methods: {len(payment_info.get('methods', []))}")
            print(f"Payment Plans: {len(payment_info.get('plans', []))}")
            print(f"Pricing Tiers: {len(payment_info.get('tiers', []))}")
            
        # Print full JSON path
        meta = results.get('scrape_metadata', {})
        print(f"\nFull results saved to: {os.path.join(RESULTS_DIR, meta.get('filename', ''))}")
    elif results and "error" in results:
        print(f"\nScrape failed: {results['error']}")
    else:
        print("\nUnknown error during scrape.") 