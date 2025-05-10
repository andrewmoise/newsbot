#!/bin/bash

cd /var/www/mbin
bin/console mbin:awesome-bot:entries:create "$@"
