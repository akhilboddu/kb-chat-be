from firecrawl import FirecrawlApp, ScrapeOptions
import json
import os
import logging
import time
import asyncio
import re
import requests
from datetime import datetime
from typing import Dict, List, Any, Optional
from urllib.parse import urlparse
from dotenv import load_dotenv
import openai

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

load_dotenv()

# Create results directory if it doesn't exist
RESULTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "results")
os.makedirs(RESULTS_DIR, exist_ok=True)

# Default configuration
DEFAULT_CONFIG = {
    "MAX_INTERNAL_PAGES": 10,  # Default number of pages to scrape
}

class Scraper:
    def __init__(self):
        """Initialize the Firecrawl scraper."""
        self.api_key = os.getenv("FIRECRAWL_API_KEY")
        if not self.api_key:
            raise ValueError("FIRECRAWL_API_KEY environment variable is not set")
        
        self.openai_api_key = os.getenv("OPENAI_API_KEY")
        if not self.openai_api_key:
            raise ValueError("OPENAI_API_KEY environment variable is not set")
        
        self.api_base_url = "https://api.firecrawl.dev/v1"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        self.start_time = None
        self.page_results = []
        self.social_links = {}
        self.config = DEFAULT_CONFIG

    def _clean_content(self, content: str) -> str:
        """Clean the content by removing image links and unnecessary elements."""
        # Remove markdown image links
        content = re.sub(r'!\[.*?\]\(.*?\)', '', content)
        # Remove HTML image tags
        content = re.sub(r'<img.*?>', '', content)
        # Remove multiple newlines
        content = re.sub(r'\n{3,}', '\n\n', content)
        # Remove extra spaces
        content = re.sub(r' {2,}', ' ', content)
        # Remove common duplicate patterns
        content = re.sub(r'(?i)(learn more|read more|click here|sign up|get started).*?(?=\n|$)', '', content)
        # Remove repeated phrases
        content = re.sub(r'(\b\w+\b)(?:\s+\1\b)+', r'\1', content)
        return content.strip()

    def _remove_duplicates(self, paragraphs: List[str]) -> List[str]:
        """Remove duplicate paragraphs and similar content."""
        unique_paragraphs = []
        seen_content = set()
        
        for para in paragraphs:
            # Normalize paragraph for comparison
            normalized = re.sub(r'\s+', ' ', para.lower().strip())
            # Skip if too short or too similar to existing content
            if len(normalized) < 20:  # Skip very short paragraphs
                continue
                
            # Check for similarity with existing content
            is_duplicate = False
            for seen in seen_content:
                # Calculate similarity (simple ratio of common words)
                words1 = set(normalized.split())
                words2 = set(seen.split())
                common_words = words1.intersection(words2)
                similarity = len(common_words) / max(len(words1), len(words2))
                
                if similarity > 0.7:  # If more than 70% similar
                    is_duplicate = True
                    break
            
            if not is_duplicate:
                unique_paragraphs.append(para)
                seen_content.add(normalized)
        
        return unique_paragraphs

    async def _process_with_llm(self, content: str) -> str:
        """Process the content with OpenAI to structure and clean it."""
        prompt = """Clean up and structure the following raw website content for use in a knowledge base. Remove duplicate or unnecessary elements like image links, repeated CTAs, and decorative text.

Important instructions:
1. Remove ALL duplicate information, even if worded slightly differently
2. If the same information appears multiple times, keep only the most complete version
3. If there are conflicting details, keep the most specific/recent information
4. Remove any repeated calls-to-action or marketing phrases
5. Consolidate similar information under single headings

Summarize key offerings clearly (e.g., bootcamps, micro-courses)

Organize the content under clear headings and bullet points

Retain important details like duration, certification, and links

Use a professional, informative tone

Ignore raw image file links unless they add informational value

Here is the content to clean and structure:
{content}"""

        try:
            response = await openai.ChatCompletion.acreate(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": "You are a helpful assistant that structures and cleans website content for knowledge bases. Your primary goal is to remove all duplicates and repetitions while maintaining the most complete and accurate information."},
                    {"role": "user", "content": prompt.format(content=content)}
                ],
                temperature=0.3,  # Lower temperature for more consistent output
                max_tokens=2000
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"Error processing content with LLM: {str(e)}")
            return content

    def _extract_social_links(self, results: List[Dict[str, Any]]) -> None:
        """Extract social media links from the crawl results."""
        social_domains = {
            "linkedin.com": "linkedin",
            "twitter.com": "twitter",
            "x.com": "twitter",
            "facebook.com": "facebook",
            "instagram.com": "instagram",
            "youtube.com": "youtube",
        }

        for result in results:
            # Extract links from the markdown content
            markdown_content = result.get("markdown", "")
            if not markdown_content:
                continue

            # Find all markdown links
            link_pattern = r'\[([^\]]+)\]\(([^)]+)\)'
            for match in re.finditer(link_pattern, markdown_content):
                href = match.group(2)
                parsed_url = urlparse(href)
                domain = parsed_url.netloc.lower()

                for social_domain, platform in social_domains.items():
                    if social_domain in domain and platform not in self.social_links:
                        self.social_links[platform] = href

    def _extract_content(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Extract and organize content from crawl results."""
        content = {
            "text_content": [],
            "urls": set(),
            "social_links": self.social_links.copy()
        }

        for result in results:
            if not result:
                continue

            # Extract markdown content
            markdown_content = result.get("markdown", "")
            if markdown_content:
                # Clean the content
                cleaned_content = self._clean_content(markdown_content)
                # Split into paragraphs
                paragraphs = [p.strip() for p in cleaned_content.split('\n\n') if p.strip()]
                content["text_content"].extend(paragraphs)

            # Extract URLs
            url = result.get("url")
            if url:
                content["urls"].add(url)

        # Remove duplicates from text content
        content["text_content"] = self._remove_duplicates(content["text_content"])
        return content

    async def _compile_flexible_business_profile(self, results: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """Compile a business profile from analyzed page results."""
        if results is None:
            results = self.page_results

        # Extract content
        content = self._extract_content(results)
        
        # Combine all text content
        full_text = "\n\n".join(content["text_content"])
        
        # Process with LLM
        structured_content = await self._process_with_llm(full_text)
        
        # Ensure we have structured content
        if not structured_content or not structured_content.strip():
            logger.warning("LLM processing returned empty content, using cleaned raw content")
            # Use cleaned content as fallback
            structured_content = full_text

        # Compile the profile
        profile = {
            "raw_content": {
                "text_content": content["text_content"],
                "urls": list(content["urls"]),
                "social_links": content["social_links"]
            },
            "structured_content": structured_content,
            "metadata": {
                "total_paragraphs": len(content["text_content"]),
                "total_urls": len(content["urls"]),
                "total_social_links": len(content["social_links"])
            }
        }

        return profile

    async def scrape(self, url: str, max_pages: Optional[int] = None) -> Dict[str, Any]:
        """Scrape a website starting from the URL and return analyzed data."""
        self.start_time = time.time()
        
        try:
            # Validate URL
            if not url.startswith(("http://", "https://")):
                url = "https://" + url

            parsed_url = urlparse(url)
            base_domain = parsed_url.netloc.replace("www.", "")

            if not base_domain or "." not in base_domain:
                raise ValueError(f"Invalid URL: {url}")

            logger.info(f"Starting scrape of: {url} (up to {max_pages} pages)")

            # Configure crawl payload
            payload = {
                "url": url,
                "maxDepth": 2,
                "ignoreSitemap": False,
                "ignoreQueryParameters": False,
                "limit": max_pages if max_pages else 1,
                "allowBackwardLinks": False,
                "allowExternalLinks": False,
                "scrapeOptions": {
                    "storeInCache": True,
                    "formats": ["markdown", "html"]
                }
            }
            logger.info(f"Configured crawl payload: {payload}")

            # Start the crawl
            logger.info("Initiating crawl request...")
            try:
                response = requests.post(
                    f"{self.api_base_url}/crawl",
                    json=payload,
                    headers=self.headers
                )
                response.raise_for_status()
                crawl_result = response.json()
                logger.info(f"Crawl request response: {crawl_result}")
            except Exception as e:
                logger.error(f"Failed to initiate crawl: {str(e)}")
                raise
            
            if not crawl_result.get("success", False):
                raise Exception(f"Failed to start crawl: {crawl_result.get('error', 'Unknown error')}")

            crawl_id = crawl_result.get("id")
            logger.info(f"Crawl started with ID: {crawl_id}")

            # Poll for results
            while True:
                try:
                    logger.info("Checking crawl status...")
                    response = requests.get(
                        f"{self.api_base_url}/crawl/{crawl_id}",
                        headers=self.headers
                    )
                    response.raise_for_status()
                    crawl_status = response.json()
                    logger.info(f"Crawl status: {crawl_status.get('status')}")
                except Exception as e:
                    logger.error(f"Failed to check crawl status: {str(e)}")
                    raise
                
                if not crawl_status.get("success", False):
                    raise Exception(f"Failed to check crawl status: {crawl_status.get('error', 'Unknown error')}")

                if crawl_status.get("status") == "completed":
                    break
                elif crawl_status.get("status") == "failed":
                    raise Exception(f"Crawl failed: {crawl_status.get('error', 'Unknown error')}")
                
                # Wait before next poll
                await asyncio.sleep(5)

            # Process results
            results = crawl_status.get("data", [])
            self.page_results = results
            logger.info(f"Received {len(results)} pages of results")

            # Extract social links from results
            self._extract_social_links(results)

            # Compile results
            result = {
                "scrape_metadata": {
                    "url": url,
                    "base_domain": base_domain,
                    "pages_scraped": len(results),
                    "scrape_time": datetime.now().isoformat(),
                    "processing_time_seconds": time.time() - self.start_time
                },
                "raw_data": results,
                "business_profile": await self._compile_flexible_business_profile()
            }

            # Save results
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_base_domain = re.sub(r"[^\w\-.]", "_", base_domain)
            filename = f"multi_page_scrape_{safe_base_domain}_{timestamp}.json"
            filepath = os.path.join(RESULTS_DIR, filename)

            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2, ensure_ascii=False)
            logger.info(f"Results saved to {filepath}")

            result["scrape_metadata"]["filename"] = filename
            return result

        except Exception as e:
            logger.exception(f"Error during scrape: {str(e)}")
            return {"error": f"Scrape failed: {str(e)}"}

# Helper function to run the scraper
async def scrape_website(url: str, max_pages: Optional[int] = None) -> Dict[str, Any]:
    """Helper function to create and run a scraper instance."""
    scraper = Scraper()
    try:
        return await scraper.scrape(url, max_pages=max_pages)
    except Exception as e:
        logger.error(f"Error during scrape: {str(e)}")
        return {"error": f"Scrape failed: {str(e)}"}

# --- Main Execution Block ---
if __name__ == "__main__":
    import sys
    import argparse

    parser = argparse.ArgumentParser(
        description="Web scraper for business profiles using Firecrawl"
    )
    parser.add_argument("url", help="URL to scrape")
    parser.add_argument(
        "--max-pages",
        type=int,
        default=8,
        help="Maximum number of internal pages to scrape (default: 15)",
    )

    if len(sys.argv) == 1:
        print("Usage: python -m src.crawler.scraper <url> [--max-pages N]")
        print("Example: python -m src.crawler.scraper https://www.example.com/ --max-pages 10")
    else:
        args = parser.parse_args()
        print(f"Starting scrape of URL: {args.url} (max pages: {args.max_pages})")
        results = asyncio.run(scrape_website(args.url, args.max_pages))

        # Print summary after scrape
        if results and "business_profile" in results and "error" not in results.get("business_profile", {}):
            print("\n--- Scrape Completed Successfully ---")
            print(f"URL: {results.get('scrape_metadata', {}).get('url', 'N/A')}")
            print(f"Pages Scraped: {results.get('scrape_metadata', {}).get('pages_scraped', 'N/A')}")
            print(f"Time: {results.get('scrape_metadata', {}).get('processing_time_seconds', 'N/A'):.2f} seconds")

            profile = results.get("business_profile", {})
            print("\n--- Business Profile (Summary) ---")
            print(f"Business Name: {profile.get('business_name', 'N/A')}")
            print(f"Tagline: {profile.get('tagline', 'N/A')}")
            print(f"Description: {profile.get('description', 'N/A')}")

            if profile.get("products"):
                print(f"Products Found: {len(profile.get('products', []))}")
            if profile.get("services"):
                print(f"Services Found: {len(profile.get('services', []))}")
            if profile.get("faqs"):
                print(f"FAQs Found: {len(profile.get('faqs', []))}")
            if profile.get("payment_options"):
                payment_info = profile.get("payment_options", {})
                print(f"Payment Methods: {len(payment_info.get('methods', []))}")
                print(f"Payment Plans: {len(payment_info.get('plans', []))}")
                print(f"Pricing Tiers: {len(payment_info.get('tiers', []))}")

            # Print full JSON path
            meta = results.get("scrape_metadata", {})
            print(f"\nFull results saved to: {os.path.join(RESULTS_DIR, meta.get('filename', ''))}")
        elif results and "error" in results:
            print(f"\nScrape failed: {results['error']}")
        else:
            print("\nUnknown error during scrape.")

