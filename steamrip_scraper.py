import requests
from bs4 import BeautifulSoup
import json
import os
from datetime import datetime
import dateutil.parser
import subprocess
import json
import re
import signal # Import the signal module

# Function to parse date strings into a consistent format
def parse_date(date_str):
    try:
        # Attempt to parse the date string
        date_obj = dateutil.parser.parse(date_str)
        # Format the date consistently (e.g., YYYY-MM-DD)
        return date_obj.strftime('%Y-%m-%d')
    except (ValueError, TypeError, OverflowError, dateutil.parser.ParserError) as e:
        print(f"Warning: Could not parse date string '{date_str}': {e}")
        return None # Return None if parsing fails

def extract_game_details(game_url, session):
    upload_date_str = None
    file_size_str = None
    download_urls = []

    try:
        response = session.get(game_url, headers=HEADERS, timeout=20) # Added HEADERS
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')

        # Extract Title (Added)
        title_str = None
        title_tag = soup.find("h1", class_="entry-title")
        if title_tag:
            title_str = title_tag.text.strip()
        else:
            # Try another common pattern for titles if the first fails
            title_tag_alt = soup.find("div", class_="post-inner") # Common container
            if title_tag_alt:
                title_h1_alt = title_tag_alt.find("h1")
                if title_h1_alt:
                    title_str = title_h1_alt.text.strip()
            
            if not title_str: # If still not found
                # Attempt to use the <title> tag from HTML head as a last resort
                html_title_tag = soup.find('title')
                if html_title_tag and html_title_tag.string:
                    # Often page titles have "» Site Name", try to clean it
                    page_title_full = html_title_tag.string.strip()
                    title_str = page_title_full.split('»')[0].strip() # Heuristic
                    if title_str:
                         print(f"Warning: Used HTML <title> tag for game title: '{title_str}' from '{page_title_full}' for {game_url}")
                    else: # If split fails or results in empty
                        title_str = page_title_full # Use full page title
                        print(f"Warning: Used full HTML <title> tag as game title: '{title_str}' for {game_url}")

            if not title_str: # If absolutely no title can be derived
                 print(f"Critical: Title still NOT FOUND for {game_url} after all fallbacks. Skipping.")
                 return None # Title is essential

        # 1. Try to get upload date from JSON-LD script tag
        json_ld_script = soup.find('script', type='application/ld+json')
        if json_ld_script and json_ld_script.string:
            try:
                ld_data = json.loads(json_ld_script.string)
                upload_date_str = ld_data.get('datePublished') or ld_data.get('dateModified')
            except json.JSONDecodeError:
                print(f"Warning: Could not parse JSON-LD from {game_url}")

        # 2. Fallback to meta tag if JSON-LD fails or no date found
        if not upload_date_str:
            meta_date = soup.find('meta', property='article:published_time')
            if meta_date and meta_date.get('content'):
                upload_date_str = meta_date['content']

        # 3. Fallback to specific span class if still no date
        if not upload_date_str:
            # Example: <span class="date meta-item tie-icon">December 23, 2024</span>
            # Example: <div class="single-post-meta post-meta clearfix"><span ...><span class="date meta-item tie-icon">DATE</span></div></div>
            date_span = soup.find('span', class_='date meta-item tie-icon')
            if date_span and date_span.get_text(strip=True):
                upload_date_str = date_span.get_text(strip=True)
            else: # Check within post-meta as well
                post_meta_div = soup.find('div', class_='single-post-meta')
                if post_meta_div:
                    date_span_in_meta = post_meta_div.find('span', class_='date meta-item tie-icon')
                    if date_span_in_meta and date_span_in_meta.get_text(strip=True):
                        upload_date_str = date_span_in_meta.get_text(strip=True)

        # 4. Fallback to searching for date in text elements with keywords
        if not upload_date_str:
            date_elements = soup.find_all(string=re.compile(r'(?:Published|Released|Date|Posted on):?\s*([A-Za-z]+\s+\d{1,2},\s+\d{4})', re.IGNORECASE))
            if date_elements:
                for de_text in date_elements:
                    match = re.search(r'([A-Za-z]+\s+\d{1,2},\s+\d{4})', de_text)
                    if match:
                        upload_date_str = match.group(1)
                        break
        
        # 5. Last resort general date regex if still no date
        if not upload_date_str:
            date_elements_general = soup.find_all(string=re.compile(r'[A-Za-z]+\s+\d{1,2},\s+\d{4}'))
            if date_elements_general:
                for de_text in date_elements_general:
                    if de_text.parent.name not in ['script', 'style', 'a', 'title'] and len(de_text.strip()) < 30: # Avoid long strings, script/style content, links, titles
                         match = re.search(r'([A-Za-z]+\s+\d{1,2},\s+\d{4})', de_text)
                         if match:
                            upload_date_str = match.group(1)
                            break

        # Extract file size
        # 1. Look for <h4>GAME INFO</h4> then <li><strong>Game Size: </strong>...</li>
        # Example: <h4><span style="font-size: 18pt;">GAME INFO</span></h4> <div class="plus tie-list-shortcode"> <ul> <li><strong>Game Size: </strong>2.8 GB</li> ...
        game_info_heading = soup.find(lambda tag: tag.name == 'h4' and 'GAME INFO' in tag.get_text(strip=True).upper())
        if game_info_heading:
            ul_container = game_info_heading.find_next_sibling('div', class_='plus tie-list-shortcode')
            if ul_container:
                ul_actual = ul_container.find('ul')
                if ul_actual:
                    for li in ul_actual.find_all('li'):
                        strong_tag = li.find('strong')
                        if strong_tag and 'Game Size:' in strong_tag.get_text(strip=True):
                            file_size_str = ''.join(sibling.string.strip() for sibling in strong_tag.next_siblings if sibling.string and sibling.string.strip())
                            if not file_size_str: 
                                file_size_str = li.get_text(strip=True).replace(strong_tag.get_text(strip=True), '').strip()
                            break
        
        # 2. Fallback for file size: text containing "Game Size:" or "Size:"
        if not file_size_str:
            size_keywords = ['Game Size:', 'Size:']
            for keyword in size_keywords:
                # Find strong tag with the keyword
                size_element_strong = soup.find('strong', string=re.compile(r'^\s*' + re.escape(keyword) + r'\s*$', re.IGNORECASE))
                if size_element_strong:
                    # The size is usually the text node immediately following the <strong> tag, within the same parent (e.g., <li>)
                    current_element = size_element_strong
                    text_after_strong = ""
                    # Iterate through next siblings to find the text node
                    for sibling in current_element.next_siblings:
                        if isinstance(sibling, str) and sibling.strip():
                            text_after_strong = sibling.strip()
                            break
                        # Sometimes it's wrapped in another tag like <span> or just text within <li>
                        elif hasattr(sibling, 'get_text') and sibling.get_text(strip=True):
                            text_after_strong = sibling.get_text(strip=True)
                            break # Take the first non-empty text found
                    
                    if text_after_strong and any(char.isdigit() for char in text_after_strong):
                        file_size_str = text_after_strong
                        break
                    elif size_element_strong.parent: # Fallback to parent's text if direct sibling fails
                        parent_text = size_element_strong.parent.get_text(strip=True)
                        # Remove the keyword part to get the value
                        value_part = parent_text.replace(size_element_strong.get_text(strip=True), '').strip()
                        if value_part and any(char.isdigit() for char in value_part):
                            file_size_str = value_part
                            break
            if not file_size_str: # Broader search if specific structure fails
                size_element = soup.find(string=re.compile(r'(?:Game Size|Size):\s*([^<\n]+(?:GB|MB|TB|KB))', re.IGNORECASE))
                if size_element:
                    match = re.search(r'(?:Game Size|Size):\s*([^<\n]+(?:GB|MB|TB|KB))', size_element, re.IGNORECASE)
                    if match:
                        file_size_str = match.group(1).strip()

        # Extract download URLs
        # Example: <a href="https://megadb.net/..." target="_blank" rel="nofollow" class="shortc-button medium purple ">DOWNLOAD HERE</a>
        # 1. Look for <a class="shortc-button ..."> or links with text "DOWNLOAD HERE"
        download_link_elements = soup.find_all('a', class_=re.compile(r'shortc-button', re.IGNORECASE))
        if not download_link_elements:
            download_link_elements = soup.find_all('a', string=re.compile(r'DOWNLOAD HERE', re.IGNORECASE))
        
        for link_element in download_link_elements:
            href = link_element.get('href')
            if href and (href.startswith('http') or href.startswith('magnet')):
                if 'javascript:void(0)' not in href.lower():
                    download_urls.append(href)
        
        # 2. Fallback: find any link within common download sections or with known hostnames
        if not download_urls:
            known_hosts = ['megadb.net', 'pixeldrain.com', 'gofile.io', '1fichier.com', 'mega.nz', 'buzzheavier.com'] # Add more if needed
            all_links = soup.find_all('a', href=True)
            for a_tag in all_links:
                href = a_tag['href']
                if href and (any(host in href for host in known_hosts)) and 'javascript:void(0)' not in href.lower():
                    download_urls.append(href)
            # Further fallback for sections
            if not download_urls:
                download_sections = soup.find_all(['div', 'p'], class_=re.compile(r'(download|links|buttons|mirror)', re.IGNORECASE))
                if not download_sections: 
                    download_sections = soup.find_all(lambda tag: (tag.name == 'div' or tag.name == 'p') and any(keyword in tag.get_text().lower() for keyword in ['download', 'mirror', 'link']))
                for section in download_sections:
                    for a_tag_sec in section.find_all('a', href=True):
                        href_sec = a_tag_sec['href']
                        if href_sec and (href_sec.startswith('http') or href_sec.startswith('magnet')):
                             if 'javascript:void(0)' not in href_sec.lower():
                                download_urls.append(href_sec)
        
        download_urls = sorted(list(set(download_urls))) # Remove duplicates and sort

    except requests.exceptions.RequestException as e:
        print(f"Error fetching {game_url}: {e}")
        return None
    except Exception as e:
        print(f"Error parsing {game_url}: {e} (Line: {e.__traceback__.tb_lineno if e.__traceback__ else 'N/A'})")
        return None

    upload_date = parse_date(upload_date_str) if upload_date_str else None
    file_size = file_size_str.strip() if file_size_str else None

    if not upload_date:
        print(f"Warning: Upload date NOT FOUND or PARSED for {game_url}. Raw date string was: '{upload_date_str}'")
    if not file_size or not any(char.isdigit() for char in file_size):
        print(f"Warning: File size NOT FOUND or INVALID for {game_url}. Raw size string was: '{file_size_str}'")
        file_size = "Unknown" # Set to unknown if not found or invalid
    if not download_urls:
        print(f"Warning: Download URLs NOT FOUND for {game_url}")

    # Process download URLs to ensure they have https:// prefix
    processed_uris = []
    for url in download_urls:
        if url.startswith('//'):
            # Convert protocol-relative URL to https
            processed_uris.append('https:' + url if url.startswith('//') else url)
        elif not url.startswith(('http://', 'https://')):
            # Add https:// if no protocol is specified
            processed_uris.append('https://' + url)
        else:
            processed_uris.append(url)
    
    # Clean up the title by removing 'Free Download' text
    clean_title = title_str.replace(' Free Download', '').replace(' free download', '').strip()
    
    if download_urls: 
        return {
            'title': clean_title,
            'uploadDate': upload_date if upload_date else "Unknown",
            'fileSize': file_size if file_size else "Unknown",
            'uris': processed_uris  # Changed from 'sources' to 'uris'
        }
    # If no download URLs, but we have a title, we might still want to return something minimal
    # or log it more clearly. For now, returning None if no URLs is fine as per existing logic.
    # However, if title is present, it means the page was likely valid.
    elif title_str: # If we got a title but no download URLs
        print(f"Warning: Found title '{clean_title}' for {game_url} but NO download URLs. Returning partial data.")
        return {
            'title': clean_title,
            'uploadDate': upload_date if upload_date else "Unknown",
            'fileSize': file_size if file_size else "Unknown",
            'uris': []  # Changed from 'sources' to 'uris'
        }
    else:
        missing_info = []
        if not upload_date: missing_info.append("upload date")
        if file_size == "Unknown": missing_info.append("file size")
        if not download_urls: missing_info.append("download URLs (critical)")
        print(f"Skipping {game_url} due to missing critical info: {', '.join(missing_info)}.")
        return None

# Configuration
BASE_URL = "https://steamrip.com"
GAME_LIST_URL = f"{BASE_URL}/games-list-page/"
LOCAL_GAME_LIST_HTML = None # To be set by command-line argument
JSON_FILE_PATH = "hydrasteam.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}


# GitHub Configuration (User needs to set these up as environment variables or secrets)
GIT_REPO_URL = os.environ.get("GIT_REPO_URL", "https://github.com/Rieversed/HydraSteam.git") # e.g., "https://username:token@github.com/username/repo.git"
GIT_USER_NAME = os.environ.get("GIT_USER_NAME", "HydraSteam Bot")
GIT_USER_EMAIL = os.environ.get("GIT_USER_EMAIL", "bot@hydrasteam.gg")

def get_soup(url):
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()  # Raise an exception for HTTP errors
        return BeautifulSoup(response.content, "html.parser")
    except requests.exceptions.RequestException as e:
        print(f"Error fetching {url}: {e}")
        return None

def parse_game_page(game_url, session): # Signature changed to accept session
    # This function now delegates all parsing to extract_game_details
    # print(f"Delegating parsing for {game_url} to extract_game_details") # Optional debug message
    return extract_game_details(game_url, session) # Pass session to extract_game_details

# The rest of the parse_game_page function (original content) is removed as it's now handled by extract_game_details.

def load_existing_downloads(filepath):
    try:
        if os.path.exists(filepath):
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                # Check if the data is a dictionary with a 'downloads' key
                if isinstance(data, dict) and 'downloads' in data and isinstance(data['downloads'], list):
                    print(f"Loaded {len(data['downloads'])} existing downloads from {filepath}")
                    return data['downloads']
                # If the file exists but has invalid format, log a warning
                elif isinstance(data, list):
                    print(f"Warning: {filepath} contains a list directly. Converting to new format.")
                    return data
                else:
                    print(f"Warning: {filepath} has an unexpected format. Starting with an empty list.")
                    return []
        else:
            print(f"No existing file found at {filepath}. Starting with an empty list.")
            return []
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON from {filepath}: {e}. Starting with an empty list.")
        return []
    except Exception as e:
        print(f"Error loading {filepath}: {e}. Starting with an empty list.")
        return []

def save_downloads(filepath, downloads_data):
    try:
        # First, try to read the existing data to preserve any non-downloads fields
        existing_data = {}
        if os.path.exists(filepath):
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    existing_data = json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                print(f"Warning: Could not read existing file {filepath}: {e}. Creating a new one.")
                existing_data = {}
        
        # Ensure we have the basic structure
        if not isinstance(existing_data, dict):
            existing_data = {}
        
        # Update the downloads list while preserving other data
        existing_data["name"] = existing_data.get("name", "HydraSteam")
        existing_data["downloads"] = downloads_data
        
        # Write the updated data back to the file
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(existing_data, f, indent=4, ensure_ascii=False)
        
        print(f"Successfully saved {len(downloads_data)} items to {filepath}")
        return True
    except Exception as e:
        print(f"Error writing to {filepath}: {e}")
        return False

def git_commit_and_push(filepath, commit_message):
    if not GIT_REPO_URL:
        print("GIT_REPO_URL not configured. Skipping GitHub commit.")
        return

    try:
        # Configure git user
        subprocess.run(["git", "config", "user.name", GIT_USER_NAME], check=True)
        subprocess.run(["git", "config", "user.email", GIT_USER_EMAIL], check=True)
        
        # Add, commit, and push
        subprocess.run(["git", "add", filepath], check=True)
        # Check if there are changes to commit
        status_result = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, check=True)
        if filepath in status_result.stdout:
            subprocess.run(["git", "commit", "-m", commit_message], check=True)
            # Ensure the remote 'origin' is set to the GIT_REPO_URL with credentials
            # It's safer to set this once manually or ensure the clone was done with the tokenized URL
            # Forcing it here can be risky if the remote name is different.
            # subprocess.run(["git", "remote", "set-url", "origin", GIT_REPO_URL], check=True)
            subprocess.run(["git", "push"], check=True) # Assumes 'origin' is correctly configured
            print(f"Successfully committed and pushed changes to GitHub for {filepath}")
        else:
            print("No changes to commit.")
    except subprocess.CalledProcessError as e:
        print(f"Git command failed: {e}")
        print(f"Stderr: {e.stderr.decode() if e.stderr else 'N/A'}")
        print(f"Stdout: {e.stdout.decode() if e.stdout else 'N/A'}")
    except FileNotFoundError:
        print("Git command not found. Ensure Git is installed and in your PATH.")

def main(local_html_path=None):
    print("Starting scraper...")
    create_json_if_not_exists()
    existing_downloads = load_existing_downloads(JSON_FILE_PATH)
    existing_titles = {game['title'] for game in existing_downloads}
    new_games_found = 0
    updated_games_count = 0
    all_downloads = list(existing_downloads) # Start with existing ones

    # Signal handler for graceful exit on Ctrl+C
    def signal_handler(sig, frame):
        print('\nCtrl+C detected. Saving progress and exiting...')
        if new_games_found > 0 or updated_games_count > 0:
            print(f"Saving {len(all_downloads)} games to {JSON_FILE_PATH} before exit...")
            save_downloads(JSON_FILE_PATH, all_downloads)
            # Optionally, you might want to commit here too, but it could be slow
            # commit_message = f"Autosave on interrupt: {new_games_found} new, {updated_games_count} updated games."
            # git_commit_and_push(JSON_FILE_PATH, commit_message)
        else:
            print("No new or updated games to save on exit.")
        exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    if local_html_path:
        print(f"Parsing local HTML file: {local_html_path}")
        try:
            with open(local_html_path, 'r', encoding='utf-8') as f:
                html_content = f.read()
            list_soup = BeautifulSoup(html_content, 'html.parser')
        except FileNotFoundError:
            print(f"Error: Local HTML file not found at {local_html_path}")
            return
        except Exception as e:
            print(f"Error parsing local HTML file: {e}")
            return
    else:
        print(f"Fetching game list from {GAME_LIST_URL}...")
        try:
            response = requests.get(GAME_LIST_URL, headers=HEADERS)
            response.raise_for_status() # Raise an exception for HTTP errors
        except requests.exceptions.RequestException as e:
            print(f"Error fetching game list page: {e}")
            return
        list_soup = BeautifulSoup(response.content, 'html.parser')

    game_links = []
    # Find all <a> tags within list items (<li>) that are likely game entries
    # This selector targets <a> tags that are direct children of <p> tags, which seems to be a common structure.
    # Adjust if the structure is different.
    # Try a few common selectors for game links on list pages
    selectors_to_try = [
        "div.all-games-list-single-item > a[href]", # Original specific selector
        "div.post-inner > div.post-content > h2.post-title > a[href]", # Common for post titles in a list
        "article.post > h2.entry-title > a[href]", # Another common article title structure
        "li.game-item > a[href]", # If games are in a list item
        "div.game-entry > a[href]", # Generic game entry container
        "a.game-link[href]" # A generic link with a class 'game-link'
    ]

    for selector in selectors_to_try:
        for link_tag in list_soup.select(selector):
            href = link_tag["href"]
            if href and href.startswith(BASE_URL) and "page" not in href and href not in game_links:
                game_links.append(href)
        if game_links: # If links are found with the current selector, no need to try others
            print(f"Found links using selector: {selector}")
            break
    
    if not game_links:
        # Fallback: try a very general selector for any link within common content containers
        # This is a last resort and might pick up non-game links, but good for debugging
        print("Primary selectors failed. Trying more general selectors...")
        for link_tag in list_soup.select("div[class*='content'] a[href], main[class*='content'] a[href], section[class*='content'] a[href]"):
             href = link_tag["href"]
             if href and href.startswith(BASE_URL) and "page" not in href and "category" not in href and "tag" not in href and href not in game_links:
                game_links.append(href)
        if game_links:
            print("Found links using very general selector.")

    print(f"Found {len(game_links)} potential game links.")

    if not game_links:
        print("No game links found on the game list page. Please check selectors.")
        # print("Page HTML for debugging selectors (first 2000 chars):\n", list_soup.prettify()[:2000]) # Uncomment for debugging HTML
        return

    # Create a copy of existing downloads to work with
    all_downloads = list(existing_downloads) # Start with existing ones
    print(f"Starting with {len(all_downloads)} existing games in the database.")

    # Track the titles we've already processed to avoid duplicates
    existing_titles = {game.get('title', '').lower() for game in all_downloads}
    print(f"Found {len(existing_titles)} unique game titles in existing data.")

    # Create a session object to reuse TCP connections
    with requests.Session() as session:
        session.headers.update(HEADERS) # Set headers for the session

        try:
            for idx, game_url in enumerate(game_links):
                print(f"\nProcessing {idx+1}/{len(game_links)}: {game_url}")
                game_data = parse_game_page(game_url, session)
                
                if game_data:
                    # Normalize the title for comparison
                    game_title = game_data.get('title', '').strip()
                    if not game_title:
                        print("Warning: Game data has no title, skipping.")
                        continue
                        
                    game_title_lower = game_title.lower()
                    
                    # Check if game already exists by title (case-insensitive)
                    game_exists_at_index = -1
                    for i, existing_game in enumerate(all_downloads):
                        if existing_game.get('title', '').lower() == game_title_lower:
                            game_exists_at_index = i
                            break
                    
                    if game_exists_at_index != -1:
                        # Game exists, check if it needs update
                        existing_game = all_downloads[game_exists_at_index]
                        if existing_game != game_data:
                            all_downloads[game_exists_at_index] = game_data
                            print(f"Updated existing game: {game_title}")
                            updated_games_count += 1
                        else:
                            print(f"No changes detected for: {game_title}")
                    else:
                        # Game does not exist, add it
                        all_downloads.append(game_data)
                        existing_titles.add(game_title_lower)
                        new_games_found += 1
                        print(f"Added new game: {game_title}")
                else:
                    print(f"Skipping game due to missing data or error: {game_url}")
                    
        except Exception as e:
            print(f"Error during processing: {e}")
            import traceback
            traceback.print_exc()
            
        finally:
            print(f"\nProcessing complete. Found {new_games_found} new and updated {updated_games_count} existing games.")
            
            if new_games_found > 0 or updated_games_count > 0:
                print(f"Saving {len(all_downloads)} games to {JSON_FILE_PATH}...")
                if save_downloads(JSON_FILE_PATH, all_downloads):
                    print("Successfully saved game data to JSON file.")
                    
                    commit_parts = []
                    if new_games_found > 0:
                        commit_parts.append(f"{new_games_found} new")
                    if updated_games_count > 0:
                        commit_parts.append(f"{updated_games_count} updated")
                    
                    if not commit_parts:
                        commit_message = "Update game list: Minor changes."
                    else:
                        commit_message = f"Update game list: {', '.join(commit_parts)} games."
                    
                    git_commit_and_push(JSON_FILE_PATH, commit_message)
                else:
                    print("Error: Failed to save game data to JSON file.")
            else:
                print("No new or updated games found to save.")

    print("Scraper finished.")

# Moved create_json_if_not_exists to be defined before main or ensure it's globally available if main calls it.
# The original placement was fine as it's defined globally before the second __main__ block.
# This change is more about consolidating the __main__ execution block.

def create_json_if_not_exists():
    if not os.path.exists(JSON_FILE_PATH):
        print(f"JSON file not found at {JSON_FILE_PATH}. Creating a new one.")
        with open(JSON_FILE_PATH, 'w', encoding='utf-8') as f:
            # Initial structure based on the user-provided steamrip_downloads.json
            # and common Hydra Launcher source structure
            initial_data = {
                "name": "SteamRip",
                "downloads": []
            }
            json.dump(initial_data, f, indent=4)
        print(f"Created {JSON_FILE_PATH}")
    else:
        # Ensure the file is valid JSON and has the 'downloads' key
        try:
            with open(JSON_FILE_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if 'downloads' not in data or not isinstance(data['downloads'], list):
                print(f"Warning: {JSON_FILE_PATH} is missing 'downloads' list or is malformed. Re-initializing.")
                # Re-initialize with a basic structure if malformed
                initial_data = {
                    "name": "SteamRip",
                    "downloads": []
                }
                with open(JSON_FILE_PATH, 'w', encoding='utf-8') as f:
                    json.dump(initial_data, f, indent=4)
        except json.JSONDecodeError:
            print(f"Error: {JSON_FILE_PATH} is not valid JSON. Re-initializing.")
            initial_data = {
                "name": "SteamRip",
                "downloads": []
            }
            with open(JSON_FILE_PATH, 'w', encoding='utf-8') as f:
                json.dump(initial_data, f, indent=4)

if __name__ == "__main__":
    import argparse # Ensure argparse is imported here for this block
    parser = argparse.ArgumentParser(description="Scrape game info from SteamRIP.")
    parser.add_argument('--local-html', type=str, help='Path to a local HTML file for the game list page.')
    args = parser.parse_args()

    # GIT_REPO_URL is already defined globally and uses os.environ.get, so re-assigning from os.getenv here is redundant
    # unless specifically overriding for this execution block, which is unlikely the intent.
    # If GIT_REPO_URL needs to be dynamically set per run based on env var at execution time, 
    # the global definition using os.environ.get is standard.
    main(local_html_path=args.local_html)