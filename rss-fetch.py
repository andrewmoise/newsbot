import logging
from datetime import datetime, timedelta
import feedparser
import json
from openai import OpenAI
import os
import re
import sys
from tinydb import TinyDB, Query

"""
RSS Feed Fetcher and Rater

This script fetches RSS feeds listed in rss-feeds.txt, processes new entries,
and uses GPT-4 to rate stories based on relevance and newsworthiness.
New stories are stored in a TinyDB database for later processing.

"""

# Configure logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s',
                    handlers=[logging.FileHandler('rss-feed-log.log'),
                              logging.StreamHandler()])

logger = logging.getLogger(__name__)

# States:
#
# new -> First seen
# avail -> We've already seen it but not done anything yet
# highlight -> This is one of the relevant ones of the current crop
# old -> Too old to bother with
# queued -> We want to post this, maybe in a rollup
# post -> This is one to post
# posted -> Was already posted
# dupe -> Was posted, just part of a roundup

# Ratings:
#
# *****: 20+
# ****: 6-19
# ***: 3-5
# **: 1-2
# *: 0

# Path to the database file
DB_PATH = 'rss-feed-data.json'

# Path to the file containing RSS feed URLs
FEEDS_FILE_PATH = 'rss-feeds.txt'

# Tuning parameters
STORY_WINDOW = 120 # in minutes
MAX_STORIES_PER_WINDOW = 10
MIN_STORIES_PER_WINDOW = 8

MIN_STORIES_TO_RATE = 10
MAX_STORIES_TO_RATE = 25

def read_auth_cookie(file_path):
    try:
        with open(file_path, 'r') as file:
            return file.read().strip()
    except FileNotFoundError:
        logger.info("Auth cookie file not found.")
        return None

def sort_by_timestamp(entries):
    return sorted(entries, key=lambda x: datetime.fromisoformat(x['timestamp']), reverse=True)

def fetch_and_store_rss_feeds(db, Feed):
    # Check if the feeds file exists
    if not os.path.exists(FEEDS_FILE_PATH):
        raise Exception("RSS feeds file not found.")
    else:
        # Read the list of RSS feeds from the file
        with open(FEEDS_FILE_PATH, 'r') as file:
            feed_urls = [line.strip() for line in file.readlines() if line.strip()]

    db.update({'state': 'avail'}, Feed.state == 'new')

    new_sources = set()

    for url in feed_urls:
        logger.info(url)

        # Parse the RSS feed
        feed = feedparser.parse(url)

        for entry in feed.entries:
            try:
                id = entry.id
            except AttributeError:
                id = entry.link

            # Check if the entry is already in the database
            existing_entry = db.get(Feed.id == id)
            if not existing_entry:
                logger.info(entry.title)
                new_sources.add(url)
                
                # Add new entry to the database with a timestamp
                db.insert({
                    'feed': str(url),
                    'id': str(id),
                    'title': entry.title,
                    'link': entry.link,
                    'published': entry.published,
                    'timestamp': datetime.now().isoformat(),
                    'state': 'new',
                    'channel': feed.feed.title
                })

    # Eject entries older than a week
    one_week_ago = datetime.now() - timedelta(days=7)
    db.remove(Feed.timestamp < one_week_ago.isoformat())

    return True #len(new_sources) >= 1

def rate_stories(db, Feed, client, stories, post_count):
    with open('ratings-seed.json') as infile:
        seed_data = json.load(infile)

    current_query = ''
    for index, entry in enumerate(seed_data[0]):
        current_query += json.dumps([index, entry[1]]) + "\n"
    for index, entry in enumerate(stories):
        current_query += json.dumps([index+len(seed_data[0]), entry['title']]) + "\n"

    current_query += "\n"
    current_query += "Okay! So our task is to rate these stories, and classify them into 'us-only' (of interest\n"
    current_query += "only within the US) or 'world' (of global interest, which may include US stories of\n"
    current_query += "a sufficient level of importance.)\n"
    current_query += "\n"
    current_query += "We'll output a series of JSON-format lists, consisting of:\n"
    current_query += "  1. The index number of each story we're referencing\n"
    current_query += "  2. The star rating of the story:\n"
    current_query += "     * = very uninteresting\n"
    current_query += "    ** = meh story\n"
    current_query += "   *** = interesting story\n"
    current_query += "  **** = highly interesting story\n"
    current_query += " ***** = fascinating, highly popular story\n"
    current_query += "  3. A classification of the story; could be 'us-only' (primarily of interest\n"
    current_query += "     only inside the US) or 'world' (of global interest, although world stories can\n"
    current_query += "     also involve the US).\n"
    current_query += "  4. A tag for the topic of the story; one or two words that encapsulate what the\n"
    current_query += "     story is concerning, so that stories can be grouped and deduplicated.\n"
    current_query += "We'll have to be careful to output *only*\n"
    current_query += "the JSON lists, without discussion, since this output forms the input to a software system\n"
    current_query += "which accepts only JSON data."
    current_query += "\n"
    current_query += "The list is:\n"

    for entry in seed_data[1]:
        current_query += json.dumps(entry) + "\n"

    logger.info('--- Query')
    logger.info(current_query)

    chat_completion = client.chat.completions.create(
        messages=[
            {
                "role": "user",
                "content": current_query,
            }
        ],
        model="gpt-4-1106-preview",
    )

    logger.info('--- Completion')
    logger.info(chat_completion)

    if os.path.exists('all-queries.json'):
        with open('all-queries.json') as infile:
            query_json = json.load(infile)
    else:
        query_json = []
    query_json.append({'query': current_query,
                       'completion': chat_completion.choices[0].message.content})
    with open('all-queries.json', 'w') as outfile:
        json.dump(query_json, outfile)

    pattern = re.compile(r'^\s*\[?\s*(\[.*\])\]?,?[\s\r\n]*$')

    json_data = chat_completion.choices[0].message.content
    for line in json_data.splitlines():
        match = pattern.match(line)
        if match:
            # Extract the JSON part and load it
            try:
                entry = json.loads(match.group(1))
            except JSONDecodeError(e):
                logger.info(f"Couldn't decode: {match.group(1)}")
                return

            index, stars, category, topic = entry
            rating = len(stars)

            if index < len(seed_data[0]):
                logger.info('Relooping')
                continue

            logger.info(f"Update {stories[index-len(seed_data[0])]['title']}")
            logger.info(f"  {index} {stars} {category} {topic}")
            
            db.update({'rating': rating,
                       'category': category,
                       'topic': topic,
                       'state': 'avail'},
                      Feed.id == stories[index-len(seed_data[0])]['id'])

def find_unrated_stories(db, Feed):
    recent_entries = []
    count = 0

    for entry in sort_by_timestamp(db.search((Feed.state == 'highlight') |
                                             (Feed.state == 'avail') |
                                             (Feed.state == 'new'))):
        if count >= MAX_STORIES_TO_RATE:
            logger.info('OLD')
            db.update({'state': 'old'}, Feed.id == entry['id'])
        else:
            count += 1
            if 'rating' not in entry:
                logger.info(f"AHN: {entry['title']}")
                recent_entries.append(entry)

    return recent_entries

def pick_story(db, Feed, post_count):
    pick_entry = None
    for entry in sort_by_timestamp(db.search(
            (Feed.state == 'new') |
            (Feed.state == 'avail') |
            (Feed.state == 'highlight'))):
        if 'rating' in entry:
            if (pick_entry is None
                    or entry['rating'] > pick_entry['rating']):
                pick_entry = entry

    if pick_entry is None:
        logger.info('No story found')
        return

    logger.info('--- Best story')
    logger.info(pick_entry['title'])

    if post_count < MIN_STORIES_PER_WINDOW or pick_entry['rating'] >= 3:
        logger.info('Queueing for post')
        db.update({'state': 'post'}, (Feed.id == pick_entry['id']))
    else:
        logger.info('Not highly enough rated')

def run_cycle():
    # Init DB
    db = TinyDB(DB_PATH)
    Feed = Query()

    # First off - let's make sure we're not at the story hard limit.
    window_begin = datetime.now() - timedelta(minutes=STORY_WINDOW)

    post_count = len(db.search((Feed.state == 'posted') & (Feed.post_timestamp > window_begin.isoformat())))
    logger.info(f'Post count: {post_count}')
    if post_count >= MAX_STORIES_PER_WINDOW:
        logger.info('Too many stories; waiting before posting anything.')
        return

    for entry in db.search(Feed.state == 'post'):
        logger.info('Post already queued; waiting')
        return

    # Fetch new stuff from RSS
    fetch_and_store_rss_feeds(db, Feed)

    # Grab any number of not-yet-rated stories
    entries = find_unrated_stories(db, Feed)

    client = OpenAI(api_key=read_auth_cookie('openai-key'))

    # Rate the stories we found
    if len(entries) >= MIN_STORIES_TO_RATE:
        rate_stories(db, Feed, client, entries, post_count)

    # Pick out a story to post
    pick_story(db, Feed, post_count)


run_cycle()
