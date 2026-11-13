"""Small, sequential, cached public-page collector. No credentials or browser bypass."""
import datetime as dt
import json
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from .common import ROOT, digest, read_json, write_json

USER_AGENT = 'Mozilla/5.0 (compatible; ScenicCourseResearch/1.0; educational text collection)'


def collect(refresh=False, delay=1.5):
    sources = read_json(ROOT / 'config/sources.json')
    folder = ROOT / 'data/raw/pages'
    folder.mkdir(parents=True, exist_ok=True)
    manifest = []
    errors = []
    for source in sources:
        doc_id, url = source['doc_id'], source['url']
        path = folder / f'{doc_id}.html'
        meta_path = folder / f'{doc_id}.json'
        if path.exists() and meta_path.exists() and not refresh:
            meta = read_json(meta_path)
            if meta['url'] != url:
                raise ValueError(f'{doc_id}: cached URL differs from registry')
            if digest(path.read_bytes()) != meta['sha256']:
                raise ValueError(f'{doc_id}: cached page checksum mismatch')
            manifest.append(meta)
            print(doc_id, 'cached', flush=True)
            continue
        for attempt in range(1, 4):
            try:
                req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT, 'Accept-Language': 'zh-CN,zh;q=0.9'})
                with urllib.request.urlopen(req, timeout=30) as response:
                    body = response.read()
                    encoding = response.headers.get_content_charset() or 'utf-8'
                    meta = {**source, 'final_url': response.url, 'http_status': response.status,
                            'encoding': encoding, 'content_type': response.headers.get('Content-Type'),
                            'retrieved_at': dt.datetime.now(dt.timezone.utc).isoformat(),
                            'raw_path': path.relative_to(ROOT).as_posix(), 'bytes': len(body),
                            'sha256': digest(body), 'attempt': attempt}
                path.write_bytes(body)
                write_json(meta_path, meta)
                manifest.append(meta)
                print(doc_id, 'downloaded', len(body), flush=True)
                time.sleep(delay)
                break
            except (urllib.error.URLError, TimeoutError, OSError) as error:
                errors.append({'doc_id': doc_id, 'url': url, 'attempt': attempt, 'error': str(error)})
                print(doc_id, 'failed', attempt, str(error), flush=True)
                if isinstance(error, urllib.error.HTTPError) and error.code in (401, 403, 404, 429):
                    break
                time.sleep(delay * attempt)
    write_json(ROOT / 'data/raw/manifest.json', manifest)
    write_json(ROOT / 'outputs/qa/collection_errors.json', errors)
    if len(manifest) != len(sources):
        raise RuntimeError(f'Only {len(manifest)}/{len(sources)} pages collected; inspect collection_errors.json')
    return manifest
