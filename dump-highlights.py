from tinydb import TinyDB, Query
import json

# Path to the TinyDB JSON file
db_path = 'rss_feed_data.json'

# Load the database
db = TinyDB(db_path)
Feed = Query()

# Fetch all entries in the database
all_entries = db.search(Feed.highlight == True)

# Format and print the entries
for entry in all_entries:
    #print(f"Feed: {entry['feed']}")
    #print(f"ID: {entry['id']}")
    #print(f"Title: {entry['title']}")
    #print(f"Link: {entry['link']}")
    #print(f"Published: {entry['published']}")
    #print(f"Fetched: {entry['timestamp']}\n")
    #print()

    print(f"* {entry['title']}")
