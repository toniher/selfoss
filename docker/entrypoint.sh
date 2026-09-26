#!/bin/sh
# selfoss expects data/{cache,sqlite,favicons,thumbnails} to already exist; it
# never creates them itself. The data/ volume is typically a fresh, empty
# bind mount or named volume, so bootstrap the subdirectories on every start.
set -e
cd /var/www/htdocs/data
mkdir -p cache sqlite favicons thumbnails
# Not recursive: data/ can hold tens of thousands of thumbnails, and files
# selfoss writes are already owned by www-data.
chown www-data:www-data . cache sqlite favicons thumbnails
exec "$@"
