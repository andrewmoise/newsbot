# RSS Feed Processor and Poster

This tool fetches news stories from a given list of RSS feeds, and posts the most relevant ones (subject to deduplication and batching) to a link aggregator community.

The goal is to post a selection of relevant news, placed into broad categories (currently "usnews" and "worldnews"), avoiding duplicating particular stories or topics too readily and rounding up multiple articles about the same subject matter into a single summary post. Basically, to be sensible and useful in terms of what we decide to post. It attempts to keep a steady and sensible rate of postings while still posting high-relevance stories as soon as they are detected (in case they are time sensitive).

It uses ML via OpenAI's API for summary, classification and decision-making as to what the most relevant stories are that it's going to post.

## What you need

* Python with `feedparser`, `openai`, and `tinydb` installed.
* An OpenAI key
* A federated social media server (or other link aggregator) to post articles to

## How to use

Echo your API key to `openai-key`, and then run `run-bot.sh` and let it run. The bot posts to `mbin` via `/var/www/mbin/bin/console` when needed.

The details of the various relevant files are:

Code:

* `run-bot.sh`: Main script to run the bot
* `rss-fetch.py`: Fetch new copies of all feeds, add any new stories to the list along with ratings
* `dedup-and-post.py`: Find the most relevant story to post, do deduplication and roundup, and post if it makes sense to do so
* `submit-post.sh`: Actually make a post. You may override this depending on how you need to post stories, once they are selected.

Configuration:

* `rss-feeds.txt`: List of feeds to fetch
* `openai-key`: OpenAI API key to use

Internal data:

* `ratings-seed.json`: Examples of how to categorize and rate stories, for benefit of the LLM
* `all-queries.json`: API query log for debugging
* `rss-feed-log.log`: Script execution log for debugging
* `rss-feed-data.json`: Current set of articles fetched from RSS