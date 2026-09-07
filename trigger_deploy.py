import urllib.request
import json
import sys

URL = 'https://api.render.com/deploy/srv-daam4fm7bikc738tlmfg?key=0yLqUHNtjAg'

def trigger():
    try:
        req = urllib.request.Request(URL, method='POST')
        with urllib.request.urlopen(req) as response:
            res = response.read().decode()
            print('[Render Deploy Hook] [+] Triggered successfully! Response:', res)
            return True
    except Exception as e:
        print('[Render Deploy Hook] [!] Error triggering deploy hook:', e)
        return False

if __name__ == '__main__':
    trigger()
