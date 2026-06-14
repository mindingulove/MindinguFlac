import subprocess
import json
import time

proc = subprocess.Popen(
    ["./build/macos/MindinguflacNowPlayingHelper", "--base-url", "http://127.0.0.1:8000"],
    stdin=subprocess.PIPE
)

def send(msg):
    proc.stdin.write((json.dumps(msg) + "\n").encode())
    proc.stdin.flush()

send({
    "type": "set_now_playing",
    "title": "Test Title",
    "artist": "Test Artist",
    "duration": 100,
    "position": 0
})
send({"type": "set_playback_state", "state": 1})

time.sleep(5)
