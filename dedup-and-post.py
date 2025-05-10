from datetime import datetime, timedelta
import json
import os
import re
import requests
import subprocess

from openai import OpenAI
from tinydb import TinyDB, Query

"""
Story Deduplication and Posting

This script analyzes the rated stories from our database, checks for duplicates,
and determines the best stories to post. It handles both individual posts and
roundups of related stories, posting them to a link aggregator community.
"""

QUEUE_DELAY = 8 # in hours

def read_auth_cookie(file_path):
    try:
        with open(file_path, 'r') as file:
            return file.read().strip()
    except FileNotFoundError:
        print("Auth cookie file not found.")
        return None

def sort_by_timestamp(entries):
    return sorted(entries, key=lambda x: datetime.fromisoformat(x['timestamp']), reverse=True)

# Returns true if you found something
def try_to_dequeue(db, Feed, client):
    time_threshold = (datetime.now() - timedelta(hours=QUEUE_DELAY)).isoformat()
    for entry in db.search((Feed.state == 'queued') & (Feed.timestamp < time_threshold)):
        dequeue_story(db, Feed, client, entry)
        return True
    return False


def dequeue_story(db, Feed, client, queue_entry):
    print(f"Dequeueing old story: {queue_entry['title']}")

    if 'schedule_timestamp' in queue_entry:
        schedule_timestamp = queue_entry['schedule_timestamp']
    else:
        schedule_timestamp = queue_entry['timestamp']

    queued_entries = []
    current_query = ''

    category = {'usnews': 0, 'worldnews': 0}

    for entry in db.search((Feed.state == 'queued') &
                           ((Feed.timestamp == schedule_timestamp) |
                            (Feed.schedule_timestamp == schedule_timestamp))):
        print(f"  {entry['title']}")
        print(f"    {entry['id']}")
        current_query += f"{len(queued_entries)}: {entry['title']}\n"
        current_query += f"    {entry['link']}\n"
        queued_entries.append(entry)

        if 'category' in entry:
            category[entry['category']] += 1

    print(f"Categories: {category}")
    
    if category['worldnews'] > category['usnews']:
        category = 'worldnews'
    else:
        category = 'usnews'

    time_threshold = (datetime.now() - timedelta(hours=24)).isoformat()

    print()
    print('And checking other entries:')

    for entry in db.search(Feed.timestamp > time_threshold):
        if entry['state'] not in ('new', 'avail', 'highlight', 'queued'):
            continue
        if any(existing_entry['id'] == entry['id'] for existing_entry in queued_entries):
            continue

        print(f"  {entry['title']}")
        print(f"    {entry['id']}")
        print(f"    {entry['category']}" if 'category' in entry else '')
        current_query += f"{len(queued_entries)}: {entry['title']}\n"
        current_query += f"    {entry['link']}\n"
        current_query += f"\n"
        queued_entries.append(entry)

    current_query += "Okay! So our task is, quite simply, to collate a group of similar stories\n"
    current_query += "into a single round-up post that summarizes everything that's happened\n"
    current_query += "recently, in summary that's easier to read than repeated duplicate posts.\n"
    current_query += "\n"
    current_query += "To that end, we're going to want to output a mapping of the following fields\n"
    current_query += "in a little JSON-encoded hash. Bear in mind that this output will be read by\n"
    current_query += "an automated system, so we must be *strict* in outputting only the JSON, and\n"
    current_query += "no commentary or anything else.\n"
    current_query += "\n"
    current_query += "The values we need to be defining in the map are:\n"
    current_query += "  * 'ids': A list of IDS of stories similar to story #0 (including story #0\n"
    current_query += "           itself). This should be a list of integers in the JSON.\n"
    current_query += "  * 'title': A summary title, i.e. a consolidated headline.\n"
    current_query += "             The consolidated headline should be the headline you would give\n"
    current_query += "             to a single article that summarized everything in the combined stories.\n"
    current_query += "             Make sure to use active voice for the headline, and use a fairly similar style as the list of headlines above.\n"
    current_query += "             It should be a *string* in the JSON.\n"
    current_query += "  * 'body': A markdown-formatted list of the matching news stories that we're\n"
    current_query += "            consolidating. This can be a bulleted list, of the format:\n"
    current_query += "            '* New York Times - [Title of NYT Article](https://link/to/article)'\n"
    current_query += "            ... obviously with substitutions to the actual values. This should be\n"
    current_query += "            a string in the JSON.\n"
    current_query += "\n"
    current_query += "(The summary under 'title', if one is needed, should be a few words about\n"
    current_query += "what's going on or what's changed, based on the headlines of the stories in the roundup.)\n"
    current_query += "\n"
    current_query += "We're trying to consolidate all the stories that share the same topic (the same war\n"
    current_query += "or world event, or the same person, etc) with story #0, including story #0 itself.\n"
    current_query += "And again, the output will be read by a software system, so it needs to be strict\n"
    current_query += "JSON with nothing additional.\n"
    current_query += "\n"
    current_query += "The output JSON is:\n"

    print('--- Query')
    print(current_query)
    print()

    chat_completion = client.chat.completions.create(
        messages=[
            {
                "role": "user",
                "content": current_query,
            }
        ],
        model="gpt-4-1106-preview",
    )

    print('--- Completion')
    print(chat_completion)

    print('--- Result')
    result_str = chat_completion.choices[0].message.content
    print(result_str)

    json_data = ''
    for line in result_str.split('\n'):
        if not re.match(r'```.*', line):
            json_data += line
    json_data = json.loads(json_data)

    state = 'posted'
    post_timestamp = datetime.now().isoformat()
    for id in json_data['ids']:
        db.update({'state': state, 'post_timestamp': post_timestamp},
                   Feed.id == queued_entries[id]['id'])
        print(f"  Remove {id}: {queued_entries[id]['id']}")
        state = 'dupe'

    if len(json_data['ids']) > 1:
        print('-- Multi post')
        body = ('Here are some recent stories on the topic:\n\n'
            + json_data['body']
            + '\n\nVisit any one for the full story.')

        title = json_data['title']
        #if not re.search(r':', title):
        #    title = 'Roundup: ' + title
        post_to_mbin(['--body=' + body, 'news', category, title])
    
    else:
        print('-- Single post')
        entry = queued_entries[id]
        post_to_mbin(['--url=' + entry['link'],
                      'news',
                      category,
                      entry['title']])

def post_story(db, Feed, client):
    posted_entries = []
    time_threshold = datetime.now() - timedelta(hours=24)

    # Fetch all previous posts
    for entry in sort_by_timestamp(db.search((Feed.state == 'posted') | (Feed.state == 'queued') | (Feed.state == 'dupe'))):
        if entry['state'] == 'posted' and datetime.fromisoformat(entry['post_timestamp']) < time_threshold:
            break

        posted_entries.append(entry)

    for entry in db.search(Feed.state == 'post'):
        current_query = ''
        
        if posted_entries:
            for index, posted_entry in enumerate(posted_entries):
                current_query += f"{index}: {posted_entry['title']}\n"

            current_query += "\n"
            current_query += "Okay! So our task is, quite simply, to detect duplication among stories. We'll\n"
            current_query += "indicate a new story, and output one of the following values:\n"
            current_query += "  2: There's already a story up above covering the exact same material; we don't\n"
            current_query += "     need to publish both.\n"
            current_query += "  1: Unique story, but on the same topic as another story above, so it can wait\n"
            current_query += "     so as not to hammer the same topic.\n"
            current_query += "  0: Unique story, no duplication (or breaking news we should publish now).\n"
            current_query += "Then, in addition, we'll be outputting a 'us-only' flag on stories which are only\n"
            current_query += "of interest within the US. A global story that *involves* the US shouldn't get the\n"
            current_query += "'us-only' flag. But if it's *only* of interest to US people, it's 'us-only'.\n"
            current_query += "We'll output that all within a tuple so we can indicate which story is duplicated. So\n"
            current_query += "the possibilities are things like: (0, None, None), or (1, n, 'us-only'), or\n"
            current_query += "(1, n, None), or (2, n, 'us-only'), where n is\n"
            current_query += "one of the indices above.\n"
            current_query += "We'll have to be careful to output *only*\n"
            current_query += "the tuple, without discussion, since this output forms the input to a software system\n"
            current_query += "which accepts strict input."
            current_query += "\n"
            current_query += "The story we're classifying is:"
            current_query += "\n"
            current_query += f"{entry['title']}\n"
            current_query += "\n"
            current_query += "The result is: ("
        else:
            current_query += "\n"
            current_query += "Okay! So our task is, quite simply, to output a 'us-only' flag on stories which are only\n"
            current_query += "of interest within the US. A global story that *involves* the US shouldn't get the\n"
            current_query += "'us-only' flag. But if it's *only* of interest to US people, it's 'us-only'.\n"
            current_query += "We'll output that within a tuple -- the possibilities are\n"
            current_query += "(0, None, 'us-only') for mainly-US stories, or (0, None, None) for stories of global interest (which may still involve the US)."
            current_query += "We'll have to be careful to output *only*\n"
            current_query += "the tuple, without discussion, since this output forms the input to a software system\n"
            current_query += "which accepts strict input."
            current_query += "\n"
            current_query += "The story we're classifying is:"
            current_query += "\n"
            current_query += f"{entry['title']}\n"
            current_query += "\n"
            current_query += "The result is: ("
            
        chat_completion = client.chat.completions.create(
            messages=[
                {
                    "role": "user",
                    "content": current_query,
                }
            ],
            model="gpt-4-1106-preview",
        )

        with open('all-queries.json') as infile:
            query_json = json.load(infile)
        query_json.append({'query': current_query,
                           'completion': chat_completion.choices[0].message.content})
        with open('all-queries.json', 'w') as outfile:
            json.dump(query_json, outfile)

        print('--- Query')
        print(current_query)
        print()

        print('--- Completion')
        print(chat_completion)

        print('--- Result')
        result_str = chat_completion.choices[0].message.content
        print(result_str)

        try:
            (dupe, idx, us) = re.split(r' *, *', result_str)[0:3]
            print(f'{dupe} {idx} {us}')
        except ValueError:
            print('Unpack problem...')
            return

        dupe = int(re.search(r'\d', dupe).group())
        if dupe > 0:
            idx = int(re.search(r'\d+', idx).group())
        us = ('usnews' if re.search(r'us-only', us) else 'worldnews')

        print(f'{dupe} {idx} {us}')

        if dupe == 2:
            print('Duplicate; skipping')
            db.update({'state': 'old'}, Feed.id == entry['id'])
            return False
        elif dupe == 1:
            print('Same topic; queueing')
            if 'schedule_timestamp' in posted_entries[idx]:
                schedule_timestamp = posted_entries[idx]['schedule_timestamp']
            else:
                schedule_timestamp = datetime.fromisoformat(posted_entries[idx]['post_timestamp'])
                schedule_timestamp += timedelta(hours=QUEUE_DELAY)
                schedule_timestamp = schedule_timestamp.isoformat()

            db.update({'state': 'queued',
                       'schedule_timestamp': schedule_timestamp,
                       'category': us},
                      Feed.id == entry['id'])
                
            return False
        elif dupe == 0:
            pass # Success! We should post.
        else:
            raise Exception("Can't happen! Dupe status is " + dupe)
            
        print('Posting!')
        print(us)
        print()

        print(f"Feed: {entry['feed']}")
        print(f"ID: {entry['id']}")
        print(f"Title: {entry['title']}")
        print(f"Link: {entry['link']}")
        print(f"Published: {entry['published']}")
        print(f"Fetched: {entry['timestamp']}\n")
        print()

        # Make the POST request
        
        response = post_to_mbin(['--url=' + entry['link'],
                                 'news',
                                 us,
                                 entry['title']])
       
        # Print the response
        #print(response.status_code)
        #print(response.text)

        db.update({'state': 'posted', 'post_timestamp': datetime.now().isoformat()}, Feed.id == entry['id'])

        return True

# Mbin stuff

def post_to_mbin(args):
    print('About to post')
    subprocess.run(['./submit-post.sh', *args])
    print('Posted')

# Path to the TinyDB JSON file
db_path = 'rss-feed-data.json'

# Load the database
db = TinyDB(db_path)
Feed = Query()

client = OpenAI(
    # This is the default and can be omitted
    api_key=read_auth_cookie('openai-key')
)

if not try_to_dequeue(db, Feed, client):
    post_story(db, Feed, client)
