from datetime import datetime
import json
from tinydb import TinyDB, Query

def sort_by_timestamp(entries):
    return sorted(entries, key=lambda x: datetime.fromisoformat(x['timestamp']), reverse=True)

def sort_by_post_timestamp(entries):
    return sorted(entries, key=lambda x: datetime.fromisoformat(x['post_timestamp']), reverse=True)


# Path to the TinyDB JSON file
db_path = 'rss_feed_data.json'

# Load the database
db = TinyDB(db_path)

Feed = Query()

# Fetch all entries in the database
#all_entries = sort_by_timestamp(db.all())
all_entries = sort_by_post_timestamp(db.search((Feed.state == 'posted') | (Feed.state == 'dupe')))

category = {
    'new': 'N',
    'avail': 'A',
    'highlight': 'H',
    'old': 'O',
    'queued': 'Q',
    'post': '!',
    'posted': 'P',
    'dupe': 'D'
}

for entry in all_entries:
    timestamp = datetime.fromisoformat(entry['post_timestamp']).strftime("%m/%d %H:%M")
    #timestamp = datetime.fromisoformat(entry['timestamp']).strftime("%m/%d %H:%M")
    print(f"{category[entry['state']]} {timestamp} {entry['title']}")
    print(f"  {entry['link']}")
    if 'schedule_timestamp' in entry:
        print(f"  {entry['schedule_timestamp']}")
        if 'category' in entry:
            print(f"  {entry['category']}")
    print()

# Format and print the entries
#for entry in all_entries:
#    print(f"Feed: {entry['feed']}")
#    print(f"ID: {entry['id']}")
#    print(f"Title: {entry['title']}")
#    print(f"Link: {entry['link']}")
#    print(f"Published: {entry['published']}")
#    print(f"Fetched: {entry['timestamp']}\n")
#    print()

