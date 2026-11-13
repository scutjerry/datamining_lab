"""Cache public discovery pages and list actual article links; no search snippets as data."""
import hashlib
import json
import re
import sys
import time
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

ROOT = Path(__file__).resolve().parents[1]


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.current = None

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.current = [dict(attrs).get('href', ''), '']

    def handle_data(self, data):
        if self.current is not None:
            self.current[1] += data

    def handle_endtag(self, tag):
        if tag == 'a' and self.current is not None:
            self.links.append(self.current)
            self.current = None


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    folder = ROOT / 'data/raw/discovery'
    folder.mkdir(parents=True, exist_ok=True)
    for url in sys.argv[1:]:
        key = hashlib.sha256(url.encode()).hexdigest()[:16]
        path = folder / f'{key}.html'
        try:
            if not path.exists():
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (compatible; ScenicCourseResearch/1.0)'})
                with urllib.request.urlopen(req, timeout=25) as response:
                    path.write_bytes(response.read())
                path.with_suffix('.json').write_text(json.dumps({'url': url}, ensure_ascii=False), encoding='utf-8')
                time.sleep(1)
            text = path.read_bytes().decode('utf-8', errors='replace')
            parser = Links()
            parser.feed(text)
            print('\nURL', url)
            print('TITLE', re.findall(r'<title>(.*?)</title>', text, re.S)[:1])
            for href, title in parser.links:
                if re.search(r'/travels/[^/]+/\d+\.html|/youji/\d+|路线|游览', href + title):
                    print(urljoin(url, href), re.sub(r'\s+', ' ', title).strip()[:160])
        except Exception as error:
            print('ERROR', url, repr(error))


if __name__ == '__main__':
    main()
