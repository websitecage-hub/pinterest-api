#!/bin/bash
# End-to-end test suite for the Pinterest Media API
set -u
BASE=http://127.0.0.1:8000
DIR=/tmp/pintest
rm -rf "$DIR" && mkdir -p "$DIR"

echo "=== 1. health ==="
curl -s "$BASE/health"; echo

echo "=== 2. video pin: info + download + file ==="
curl -s "$BASE/pin/7810999345573240/info" -o "$DIR/info_video.json"
curl -s "$BASE/pin/7810999345573240/download" -o "$DIR/video.mp4" -w "download: HTTP %{http_code}, %{size_download} bytes\n"
curl -s "$BASE/pin/7810999345573240/file" -o "$DIR/file_video.json"
file "$DIR/video.mp4" | cut -c1-100

echo "=== 3. image pin ==="
curl -s "$BASE/pin/369858188161092508/download" -o "$DIR/image.jpg" -w "download: HTTP %{http_code}, %{size_download} bytes\n"
file "$DIR/image.jpg" | cut -c1-100

echo "=== 4. gif pin ==="
curl -s "$BASE/pin/840765824214269718/download" -o "$DIR/gif.gif" -w "download: HTTP %{http_code}, %{size_download} bytes\n"
file "$DIR/gif.gif" | cut -c1-100

echo "=== 5. resolve (full URL with slug) ==="
curl -s "$BASE/resolve?url=https://www.pinterest.com/pin/funny-cat-making-a-face-with-paw-in-the-air--840765824214269718" -o "$DIR/resolve.json" -w "HTTP %{http_code}\n"

echo "=== 6. zip all (video pin: all sizes + videos) ==="
curl -s "$BASE/pin/7810999345573240/download/all" -o "$DIR/all.zip" -w "zip: HTTP %{http_code}, %{size_download} bytes\n"
unzip -l "$DIR/all.zip" | tail -5

echo "=== 7. stream inline (headers check) ==="
curl -sI "$BASE/pin/369858188161092508/stream" | grep -iE "content-type|content-disposition"

echo "=== 8. bad pin id (error handling) ==="
curl -s "$BASE/pin/999999999999999999999/info" -w "\nHTTP %{http_code}\n" | head -c 300

echo
echo "=== summary ==="
file "$DIR"/* 2>/dev/null | sed "s|$DIR/||"
