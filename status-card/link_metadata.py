"""Bounded preparation of safe metadata for existing Work Links.

This is a task-private observation cache, not a provider/configuration registry.
Only explicit preparation may perform GETs; normalization and browser reads do not.
"""
import copy
import fcntl
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit

PROCESS_SECONDS = 2
PREPARE_SECONDS = 8
MAX_GETS = 8
CACHE_SECONDS = 900
FAILURE_SECONDS = 30
STATES = {'not_loaded', 'loading', 'ready', 'empty', 'unavailable', 'stale'}
REASONS = {
    'not_loaded': 'Details not loaded.', 'loading': 'Loading details…',
    'timeout': 'Details unavailable: lookup timed out.',
    'unavailable': 'Details unavailable from the configured provider.',
    'denied': 'Details unavailable: provider access denied.',
    'unsupported': 'Details unavailable for the configured repository.',
    'budget': 'Details unavailable: preparation limit reached.',
    'private': 'Description withheld from the shared card; open the tracker for details.',
    'unsafe': 'Description withheld from the shared card; open the tracker for details.',
    'empty': 'No description published.', 'ready': 'Details loaded.', 'stale': 'Last known details.',
    'configuration': 'Details unavailable: metadata authorization needs reconciliation.',
    'binding': 'Details unavailable for this item or task.',
    'candidate': 'Last known details; current candidate binding is pending.',
}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def sha(value):
    return hashlib.sha256(value).hexdigest()


def iso(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat(timespec='milliseconds')


def seconds(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('Metadata observation needs a timezone')
    return parsed.timestamp()


def compact(value, limit=500):
    if not isinstance(value, str):
        raise ValueError('Expected metadata text')
    return re.sub(r'\s+', ' ', ''.join(c for c in value if ord(c) >= 32)).strip()[:limit]


def repository(value):
    if value.startswith('git@github.com:'):
        value = 'https://github.com/' + value.split(':', 1)[1]
    u = urlsplit(value)
    if u.scheme not in ('https', 'ssh') or u.hostname != 'github.com' or u.port or u.query or u.fragment:
        raise ValueError('Unsupported configured repository')
    if u.username is not None and not (u.scheme == 'ssh' and u.username == 'git'):
        raise ValueError('Repository credentials are not metadata configuration')
    parts = u.path.strip('/').split('/')
    if len(parts) == 3 and parts[-1] in ('issues', 'pulls'):
        parts.pop()
    if len(parts) != 2:
        raise ValueError('Expected a repository pointer')
    owner, name = parts
    name = name.removesuffix('.git')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]*', owner) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', name) or name in ('.', '..'):
        raise ValueError('Invalid configured repository')
    return (owner + '/' + name).lower()


def identity(row):
    u = urlsplit(row.get('url', ''))
    if u.scheme != 'https' or u.hostname != 'github.com' or u.port or u.username is not None or u.password is not None or u.query or '\\' in row.get('url', ''):
        raise ValueError('Unsupported item destination')
    match = re.fullmatch(r'/([^/]+)/([^/]+)/(issues|pull)/([1-9][0-9]*)/?', u.path)
    if not match or row.get('kind') not in ('epic', 'issue', 'pr'):
        raise ValueError('Unsupported item identity')
    owner, name, route, number = match.groups()
    repo = repository(f'https://github.com/{owner}/{name}')
    if (row['kind'] == 'pr') != (route == 'pull'):
        raise ValueError('Item kind does not match destination')
    return {'repository': repo, 'number': int(number), 'kind': row['kind'],
            'url': f'https://github.com/{repo}/{route}/{int(number)}'}


def row_digest(row):
    value = {k: row.get(k) for k in ('kind', 'label', 'url', 'flight', 'title', 'description', 'created_at', 'updated_at')}
    value['description'] = value['description'] or None
    return sha(canonical(value))


class Unavailable(Exception):
    def __init__(self, reason='unavailable'):
        self.reason = reason


def command(args, deadline):
    remaining = min(PROCESS_SECONDS, deadline - time.monotonic())
    if remaining <= 0:
        raise Unavailable('timeout')
    try:
        process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, start_new_session=True)
        try:
            out, err = process.communicate(timeout=remaining)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                process.communicate(timeout=0.2)
            except subprocess.TimeoutExpired:
                process.stdout.close()
                process.stderr.close()
            raise Unavailable('timeout')
    except OSError:
        raise Unavailable()
    if process.returncode:
        # Raw errors can contain host paths, response bodies or credentials.
        raise Unavailable('denied' if re.search(rb'\b(401|403)\b', err) else 'unavailable')
    if len(out) > 2 * 1024 * 1024:
        raise Unavailable()
    return out


def context(project, deadline):
    project = Path(project).resolve()
    revision = 'source-remote'
    configured = None
    config = project / '.flightcheck/project.json'
    if config.exists():
        # Consume the delivered read-only common model; never update/migrate it.
        candidates = [project / '.flightcheck/scripts/project_config.py',
                      Path(__file__).resolve().parents[1] / 'workflow/scripts/project_config.py']
        path = next((p for p in candidates if p.is_file()), None)
        if path is None:
            raise Unavailable('unsupported')
        spec = importlib.util.spec_from_file_location('card_project_config', path)
        model = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(model)
            snapshot = model.snapshot(project)
            revision = snapshot['revision']
            resources = snapshot['values'].get('resources', {})
            configured = resources.get('repository') or resources.get('issue_tracker')
        except (OSError, ValueError, KeyError, TypeError):
            raise Unavailable('unsupported')
    common = command(['/usr/bin/git', '--no-optional-locks', '-C', str(project), 'rev-parse', '--git-common-dir'], deadline).decode().strip()
    if configured is None:
        remotes = command(['/usr/bin/git', '--no-optional-locks', '-C', str(project), 'remote'], deadline).decode().split()
        if len(remotes) != 1:
            raise Unavailable('unsupported')
        configured = command(['/usr/bin/git', '--no-optional-locks', '-C', str(project), 'remote', 'get-url', remotes[0]], deadline).decode().strip()
    try:
        repo = repository(configured)
    except (TypeError, ValueError):
        raise Unavailable('unsupported')
    authority = sha(canonical({'repository': repo, 'common_git': str((project / common).resolve()), 'configuration_revision': revision}))
    return {'repository': repo, 'authority': authority}


def private_directory(path):
    path = Path(path)
    parent = path.parent
    if parent.is_symlink() or parent.stat().st_uid != os.geteuid() or parent.stat().st_mode & 0o077:
        raise Unavailable('unavailable')
    if path.is_symlink():
        raise Unavailable()
    path.mkdir(mode=0o700, exist_ok=True)
    if path.stat().st_uid != os.geteuid() or path.stat().st_mode & 0o077:
        raise Unavailable()
    return path


def cache_read(path, task, authority, key):
    try:
        if path.is_symlink() or path.stat().st_uid != os.geteuid() or path.stat().st_mode & 0o077:
            return None
        value = json.loads(path.read_bytes())
        if not isinstance(value, dict) or value.get('schema') != 1 or value.get('task') != task or value.get('authority') != authority or value.get('identity') != key:
            return None
        for name in ('observed_at', 'failed_at'):
            if name in value and (type(value[name]) not in (int, float) or not math.isfinite(value[name])):
                return None
        safe = value.get('safe')
        if safe is not None:
            if (not isinstance(safe, dict) or set(safe) != {'title', 'description', 'description_state', 'provider_state', 'created_at', 'updated_at'}
                    or value.get('safe_sha256') != sha(canonical(safe)) or 'observed_at' not in value
                    or not isinstance(safe['title'], str) or not safe['title'] or len(safe['title']) > 500
                    or not isinstance(safe['description'], str) or len(safe['description']) > 240
                    or safe['description_state'] not in ('ready', 'empty', 'private', 'unsafe')
                    or safe['provider_state'] not in ('open', 'closed', 'merged')):
                return None
            seconds(safe['created_at']); seconds(safe['updated_at'])
        elif key.get('number') is None and (type(value.get('private')) is not bool or 'observed_at' not in value):
            return None
        return value
    except (OSError, ValueError, TypeError):
        return None


def cache_write(path, value):
    lock_path = path.parent / 'cache.lock'
    if path.is_symlink() or lock_path.is_symlink():
        raise Unavailable()
    if lock_path.exists() and (lock_path.stat().st_uid != os.geteuid() or lock_path.stat().st_mode & 0o077):
        raise Unavailable()
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        prior = cache_read(path, value['task'], value['authority'], value['identity'])
        if prior and prior.get('safe') and value.get('safe'):
            old_version = prior['safe'].get('updated_at', '')
            new_version = value['safe'].get('updated_at', '')
            if old_version > new_version or (old_version == new_version and prior.get('observed_at', 0) > value.get('observed_at', 0)):
                return prior
        fd, pending = tempfile.mkstemp(prefix='.metadata-', dir=path.parent)
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump(value, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(pending, path)
        finally:
            Path(pending).unlink(missing_ok=True)
    return value


def sensitive(text):
    pattern = r'(?i)(?:\b(?:secret|password|authorization|confidential|private[_ -]?body|api[_ -]?key|access[_ -]?token)\b|(?:/Users/|/home/|/private/|[A-Z]:\\)|\b(?:gh[pousr]_|sk-)[A-Za-z0-9_-]{8,})'
    return bool(re.search(pattern, text))


def summary(body, private):
    if body is not None and not isinstance(body, str):
        raise Unavailable()
    if body is None or not body.strip():
        return '', 'empty'
    if private:
        return '', 'private'
    text = re.sub(r'```.*?```', '', body, flags=re.S)
    text = re.sub(r'<!--.*?-->', '', text, flags=re.S)
    paragraphs = [p.strip() for p in re.split(r'\n\s*\n', text) if p.strip() and not p.lstrip().startswith('#')]
    if not paragraphs:
        return '', 'unsafe'
    text = paragraphs[0]
    if sensitive(text):
        return '', 'unsafe'
    text = re.sub(r'!\[[^\]]*\]\([^)]*\)', '', text)
    text = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', text)
    text = re.sub(r'<[^>]*>', '', text)
    text = re.sub(r'[`*_~]', '', text)
    text = re.sub(r'https?://\S+', '', text)
    text = compact(text, 240)
    return (text, 'ready') if text else ('', 'unsafe')


def provider_get(endpoint, deadline, budget):
    if budget[0] >= MAX_GETS:
        raise Unavailable('budget')
    budget[0] += 1
    try:
        return json.loads(command(['gh', 'api', '--hostname', 'github.com', '--method', 'GET', endpoint], deadline))
    except (ValueError, TypeError):
        raise Unavailable()


def source_payload(response, key, private):
    actual = identity({'kind': key['kind'], 'url': response.get('html_url', '')})
    if actual != key or response.get('number') != key['number']:
        raise Unavailable('binding')
    if key['kind'] != 'pr' and response.get('pull_request') is not None:
        raise Unavailable('binding')
    title = compact(response.get('title'))
    if not title:
        raise Unavailable()
    if sensitive(title):
        raise Unavailable('unsafe')
    description, state = summary(response.get('body'), private)
    payload = {'title': title, 'description': description, 'description_state': state,
               'provider_state': 'merged' if response.get('merged_at') else response.get('state')}
    if payload['provider_state'] not in ('open', 'closed', 'merged'):
        raise Unavailable()
    for name in ('created_at', 'updated_at'):
        value = response.get(name)
        try:
            payload[name] = iso(seconds(value))
        except (ValueError, TypeError, AttributeError, OverflowError):
            raise Unavailable()
    return payload


def bind(row, task, candidate, key=None, entry=None, reason=None, stale=False):
    result = copy.deepcopy(row)
    result.pop('metadata', None)
    safe = entry.get('safe') if entry else None
    if safe:
        for name in ('title', 'description', 'created_at', 'updated_at'):
            result[name] = safe[name]
        state = 'stale' if stale else safe['description_state']
        state = state if state in ('ready', 'empty', 'stale') else 'unavailable'
        why = reason or (safe['description_state'] if state == 'unavailable' else state)
    else:
        state, why = 'unavailable' if reason else 'not_loaded', reason or 'not_loaded'
    if key is None:
        try:
            key = identity(row)
        except ValueError:
            pass
    meta = {'schema': 1, 'task': task, 'candidate': candidate, 'identity': key,
            'state': state, 'ready': state in ('ready', 'empty'),
            'reason': REASONS.get(why, REASONS['unavailable']), 'source': 'cache' if stale else 'prepared'}
    if safe:
        meta.update(observed_at=iso(entry['observed_at']), expires_at=iso(entry['observed_at'] + CACHE_SECONDS),
                    provider_state=safe['provider_state'])
    meta['content_sha256'] = row_digest(result)
    result['metadata'] = meta
    return result


def normalize(row, task=None, candidate=None, now=None):
    """Pure allowlisted public projection; no cache/provider access."""
    result = copy.deepcopy(row)
    value = row.get('metadata')
    now = time.time() if now is None else now
    if value is None:
        result['metadata'] = {'schema': 1, 'state': 'not_loaded', 'ready': False, 'reason': REASONS['not_loaded']}
        return result
    try:
        if not isinstance(value, dict) or value.get('schema') != 1 or value.get('state') not in STATES:
            raise ValueError('Invalid metadata observation')
        allowed = {'schema', 'task', 'candidate', 'identity', 'state', 'ready', 'reason', 'source',
                   'observed_at', 'expires_at', 'provider_state', 'content_sha256'}
        meta = {k: v for k, v in value.items() if k in allowed}
        if meta.get('provider_state') not in (None, 'open', 'closed', 'merged'):
            raise ValueError('Invalid provider state')
        if meta.get('source') not in (None, 'cache', 'prepared'):
            raise ValueError('Invalid metadata source')
        if meta.get('reason') not in set(REASONS.values()) | {'Last known details; refresh is due.'}:
            meta['reason'] = REASONS['unavailable']
        # A bounded unavailable/unloaded observation need not invent a source identity.
        if not meta.get('identity') and meta['state'] in ('not_loaded', 'unavailable'):
            result['metadata'] = {k: meta[k] for k in ('schema', 'state', 'reason')}
            result['metadata']['ready'] = False
            return result
        key = identity(row)
        if (meta.get('identity') != key or meta.get('content_sha256') != row_digest(row)
                or (task is not None and meta.get('task') != task)):
            raise ValueError('Wrong metadata binding')
        if candidate is not None and meta.get('candidate') != candidate:
            meta.update(state='stale', ready=False, reason=REASONS['candidate'])
        if meta.get('observed_at') is not None:
            observed, expiry = seconds(meta['observed_at']), seconds(meta['expires_at'])
            if observed > now + 5 or expiry < observed:
                raise ValueError('Invalid metadata age')
            if now >= expiry and meta['state'] in ('ready', 'empty'):
                meta.update(state='stale', ready=False, reason='Last known details; refresh is due.')
        elif meta['state'] in ('ready', 'empty', 'stale'):
            raise ValueError('Loaded metadata requires its observation age')
        if meta['state'] == 'loading' and (not meta.get('expires_at') or now >= seconds(meta['expires_at'])):
            meta.update(state='unavailable', ready=False, reason=REASONS['timeout'])
        meta['ready'] = meta['state'] in ('ready', 'empty')
        result['metadata'] = meta
        return result
    except (KeyError, ValueError, TypeError, AttributeError, OverflowError):
        result.pop('title', None)
        result.pop('description', None)
        result['metadata'] = {'schema': 1, 'state': 'unavailable', 'ready': False, 'reason': REASONS['binding']}
        return result


def prepare_links(links, cache_dir, project, task, candidate, *, fetch=True, now=None, refresh=False):
    """Resolve one bounded batch before publication; no operation grants writes."""
    if not links:
        return []
    now = time.time() if now is None else now
    deadline, budget = time.monotonic() + PREPARE_SECONDS, [0]
    try:
        cache = private_directory(cache_dir)
        scope = context(project, deadline)
    except (Unavailable, OSError, ValueError) as error:
        why = error.reason if isinstance(error, Unavailable) else 'unavailable'
        return [bind(row, task, candidate, reason=why) for row in links]
    visibility = None
    result = []
    for row in links:
        try:
            key = identity(row)
            if key['repository'] != scope['repository']:
                raise Unavailable('unsupported')
        except (ValueError, Unavailable) as error:
            result.append(bind(row, task, candidate, reason=getattr(error, 'reason', 'unsupported')))
            continue
        path = cache / ('item-' + sha(canonical(key)) + '.json')
        prior = cache_read(path, task, scope['authority'], key)
        if prior and prior.get('safe') and not refresh and now < prior['observed_at'] + CACHE_SECONDS:
            result.append(bind(row, task, candidate, key, prior))
            continue
        if not fetch or (prior and now < prior.get('failed_at', -FAILURE_SECONDS) + FAILURE_SECONDS):
            result.append(bind(row, task, candidate, key, prior, reason=prior.get('reason') if prior else None, stale=bool(prior and prior.get('safe'))))
            continue
        try:
            if visibility is None:
                # Cached public visibility cannot classify newly fetched bodies.
                # Recheck once per acquisition batch; safe item-cache hits above
                # still perform no provider read.
                response = provider_get('repos/' + scope['repository'], deadline, budget)
                if response.get('full_name', '').lower() != scope['repository'] or type(response.get('private')) is not bool:
                    raise Unavailable('binding')
                visibility = response['private']
            route = 'pulls' if row['kind'] == 'pr' else 'issues'
            response = provider_get(f'repos/{scope["repository"]}/{route}/{key["number"]}', deadline, budget)
            safe = source_payload(response, key, visibility)
            entry = {'schema': 1, 'task': task, 'authority': scope['authority'], 'identity': key,
                     'observed_at': now, 'safe': safe, 'safe_sha256': sha(canonical(safe))}
            entry = cache_write(path, entry)
            result.append(bind(row, task, candidate, key, entry))
        except (Unavailable, OSError, ValueError, TypeError, AttributeError) as error:
            why = error.reason if isinstance(error, Unavailable) else 'unavailable'
            entry = dict(prior or {'schema': 1, 'task': task, 'authority': scope['authority'], 'identity': key}, failed_at=now, reason=why)
            try:
                cache_write(path, entry)
            except (OSError, Unavailable):
                pass
            result.append(bind(row, task, candidate, key, entry, reason=why, stale=bool(entry.get('safe'))))
    return result


def prepare_publication(path, data, details, project=None, *, fetch=True):
    """Controller/changed-link preparation only, called outside card.lock."""
    if data.get('mode') != 'flight' or 'links' not in details:
        return copy.deepcopy(details)
    # Existing schema validation happens before any provider read.
    from task_details import link, task_id, short_text
    task_id(data['task']); short_text(data['candidate'])
    links = [link(row) for row in details['links']]
    result = copy.deepcopy(details)
    result['links'] = prepare_links(links, Path(path).parent / 'link-metadata', project or Path.cwd(),
                                    data['task'], data['candidate'], fetch=fetch)
    return result


def association_key(rows):
    return [(r.get('kind'), r.get('label'), r.get('url'), r.get('flight')) for r in rows]


def check_publication_base(before, current, data, details):
    """A delayed lookup cannot overwrite a newer task/candidate/link selection."""
    if not current:
        return
    if current['task'] != data['task']:
        raise ValueError('Metadata preparation belongs to another task')
    if current['candidate'] != before.get('candidate') and current['candidate'] != data['candidate']:
        raise ValueError('Candidate changed during metadata preparation')
    if ('links' in details and association_key(current.get('links', [])) != association_key(before.get('links', []))
            and association_key(details['links']) != association_key(current.get('links', []))):
        raise ValueError('Links changed during metadata preparation')
