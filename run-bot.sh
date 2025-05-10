#!/bin/bash

while true; do
    pyenv/bin/python rss-fetch.py || break
    pyenv/bin/python dedup-and-post.py || break
    sleep 600 # 10 minutes
done
