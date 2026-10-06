"""Migration precheck as a pinned tool, a closed filename contract and separate verdicts (INV-MIGRATION-001).

The upstream Flyway collision checker compared only the first number of a version, overwrote the
vendor list of every earlier module with the last one, exited 0 after an arithmetic error on V08,
reported an unreadable folder as success and never listed the colliding files. Here the tool and
its version are pinned; a file name is either supported and normalized or refused by name; every
configured location is identified by module, vendor and path and classified (found, empty,
missing, unreadable); filename parity, SQL content, applied history and the live schema are four
separate results; an applied version is immutable and a new version is reconciled against the
history actually read at apply time under the control-plane lock.
"""
import re

from codex_harness.domain.model import ContractError, digest, require

TOOL = {'name': 'zeus-sql-migrator', 'version': 1, 'filename_contract': 'V?<n>(.<n>|_<n>)*(__<description>)?.sql'}
VENDORS = ('postgres', 'mysql', 'sqlite')
LOCATION_STATES = ('found', 'empty', 'missing', 'unreadable')
RESULT_STATUSES = ('ok', 'refused', 'not_applicable', 'unknown')
NAME = re.compile(r'V?(?P<version>\d+(?:[._]\d+)*)(?:__(?P<description>[A-Za-z0-9][A-Za-z0-9_-]{0,119}))?\.sql\Z')
TOKEN = re.compile(r'[a-z][a-z0-9_-]{0,63}\Z')
MAX_SQL_BYTES = 4 * 1024 * 1024


def parse_version(name):
    """Normalize a supported file name; anything else is refused by name, never skipped."""
    require(type(name) is str and name, 'Migration file name must be text')
    if not name.endswith('.sql'):
        raise ContractError(f'{name}: unsupported (only lowercase .sql files are migrations)')
    match = NAME.fullmatch(name)
    if not match:
        raise ContractError(f'{name}: unsupported name; contract is {TOOL["filename_contract"]}')
    parts = [int(p) for p in re.split(r'[._]', match.group('version'))]
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()  # 1.0 and 1 are the same version, as in Flyway
    return {'name': name, 'version': parts, 'label': '.'.join(str(p) for p in parts),
            'description': match.group('description') or ''}


def parse_config(config):
    """Closed location configuration: module, vendor, path and whether the scope is required."""
    if isinstance(config, dict):
        config = {k: v for k, v in config.items() if k != 'config_hash'}  # a parsed config re-parses to itself
    require(isinstance(config, dict) and set(config) <= {'version', 'target_vendor', 'locations', 'expected_tables'}
            and config.get('version') == 1, 'Migration config requires version 1')
    require(config.get('target_vendor') in VENDORS, 'Migration config requires a supported target_vendor')
    locations = config.get('locations')
    require(isinstance(locations, list) and locations, 'Migration config requires at least one location')
    parsed, seen = [], set()
    for entry in locations:
        require(isinstance(entry, dict) and set(entry) <= {'module', 'vendor', 'path', 'required', 'allow_empty'}
                and {'module', 'vendor', 'path'} <= set(entry), 'Location requires module, vendor, path')
        require(type(entry['module']) is str and TOKEN.fullmatch(entry['module']), 'Location module must be a token')
        require(entry['vendor'] in VENDORS, 'Location vendor must be supported')
        require(type(entry['path']) is str and entry['path'] and '..' not in entry['path'].replace('\\', '/').split('/'),
                'Location path must be a relative path inside the root')
        require(type(entry.get('required', True)) is bool and type(entry.get('allow_empty', False)) is bool,
                'required and allow_empty must be booleans')
        key = (entry['module'], entry['vendor'], entry['path'])
        require(key not in seen, f'Duplicate location {key}')
        seen.add(key)
        parsed.append({'module': entry['module'], 'vendor': entry['vendor'], 'path': entry['path'],
                       'required': entry.get('required', True), 'allow_empty': entry.get('allow_empty', False)})
    tables = config.get('expected_tables', [])
    require(isinstance(tables, list) and all(type(t) is str and TOKEN.fullmatch(t) for t in tables), 'expected_tables must be identifiers')
    require(any(loc['vendor'] == config['target_vendor'] for loc in parsed), 'No location serves the target vendor')
    return {'version': 1, 'target_vendor': config['target_vendor'], 'locations': parsed, 'expected_tables': sorted(set(tables)),
            'config_hash': digest({'target_vendor': config['target_vendor'], 'locations': parsed, 'expected_tables': sorted(set(tables))})}


def classify_location(location, observation):
    """One configured location against what discovery actually saw; a missing scope is never empty."""
    require(isinstance(observation, dict) and observation.get('state') in LOCATION_STATES, 'Location observation requires a state')
    files, ignored, refused = [], [], []
    for entry in observation.get('files', []):
        if not entry['name'].lower().endswith('.sql'):
            ignored.append(entry['name'])
            continue
        try:
            version = parse_version(entry['name'])
        except ContractError as exc:
            refused.append(str(exc))
            continue
        files.append({**version, 'bytes': entry['bytes'], 'checksum': entry.get('checksum'), 'error': entry.get('error')})
    state = observation['state']
    if state == 'found' and not files and not refused:
        state = 'empty'
    status = 'ok'
    if state == 'missing' or state == 'unreadable' or refused:
        status = 'refused' if location['required'] or refused else 'not_applicable'
    elif state == 'empty' and not location['allow_empty']:
        status = 'refused' if location['required'] else 'not_applicable'
    return {'module': location['module'], 'vendor': location['vendor'], 'path': location['path'], 'required': location['required'],
            'state': state, 'status': status, 'files': sorted(files, key=lambda f: (f['version'], f['name'])), 'ignored': sorted(ignored),
            'refused_names': refused, 'error': observation.get('error')}


def _duplicates(files):
    by_version = {}
    for entry in files:
        by_version.setdefault(entry['label'], []).append(entry['name'])
    return {label: names for label, names in by_version.items() if len(names) > 1}


def evaluate(config, observations, history=None, live_tables=None):
    """Four separate results plus the location denominator; apply is allowed only when every result is ok."""
    config = parse_config(config)
    require(isinstance(observations, dict), 'Observations map "module/vendor/path" to discovery results')
    locations = []
    for location in config['locations']:
        key = f"{location['module']}/{location['vendor']}/{location['path']}"
        observation = observations.get(key)
        if observation is None:
            locations.append({**location, 'state': 'unknown', 'status': 'refused' if location['required'] else 'not_applicable',
                              'files': [], 'ignored': [], 'refused_names': [], 'error': 'location not discovered; unknown is not approval'})
            continue
        locations.append(classify_location(location, observation))
    # Result 1: file names per module/vendor (nothing overwritten; duplicates list every colliding file).
    by_module_vendor = {}
    for loc in locations:
        by_module_vendor.setdefault((loc['module'], loc['vendor']), []).extend(loc['files'])
    filenames = {'status': 'ok', 'scopes': {}}
    for (module, vendor), files in sorted(by_module_vendor.items()):
        duplicates = _duplicates(files)
        filenames['scopes'][f'{module}/{vendor}'] = {'versions': [f['label'] for f in sorted(files, key=lambda f: f['version'])],
                                                     'duplicates': duplicates}
        if duplicates:
            filenames['status'] = 'refused'
    if any(loc['refused_names'] for loc in locations):
        filenames['status'] = 'refused'
    # Result 2: parity across the vendors of one module (single vendor: not applicable, not ok).
    parity = {'status': 'not_applicable', 'modules': {}}
    for module in sorted({loc['module'] for loc in locations}):
        module_locations = [loc for loc in locations if loc['module'] == module]
        observed = {loc['vendor'] for loc in module_locations} - {loc['vendor'] for loc in module_locations if loc['state'] not in {'found', 'empty'}}
        unobserved = sorted({loc['vendor'] for loc in module_locations} - observed)
        unobserved_required = sorted({loc['vendor'] for loc in module_locations if loc['vendor'] in unobserved and loc['required']})
        vendors = {v: {f['label'] for f in files} for (m, v), files in by_module_vendor.items() if m == module and v in observed}
        if unobserved_required:
            parity['modules'][module] = {'status': 'unknown', 'vendors': sorted(observed), 'unobserved': unobserved,
                                         'note': 'a required vendor scope was not observed; parity is unknown, not ok'}
        elif len(vendors) < 2:
            parity['modules'][module] = {'status': 'not_applicable', 'vendors': sorted(observed), 'unobserved': unobserved}
        else:
            union = set().union(*vendors.values())
            missing = {v: sorted(union - present, key=lambda s: [int(p) for p in s.split('.')]) for v, present in vendors.items() if union - present}
            parity['modules'][module] = {'status': 'refused' if missing else 'ok', 'vendors': sorted(observed), 'unobserved': unobserved, 'missing': missing}
    statuses = {m['status'] for m in parity['modules'].values()}
    parity['status'] = 'refused' if 'refused' in statuses else 'unknown' if 'unknown' in statuses else 'ok' if 'ok' in statuses else 'not_applicable'
    # Result 3: SQL content of the target vendor (empty, oversized and undecodable files are named).
    target = sorted(({**f, 'module': loc['module']} for loc in locations if loc['vendor'] == config['target_vendor'] for f in loc['files']),
                    key=lambda f: (f['module'], f['version'], f['name']))
    content = {'status': 'ok', 'files': []}
    for entry in target:
        problem = entry.get('error') or ('empty file' if entry['bytes'] == 0 else 'exceeds size cap' if entry['bytes'] > MAX_SQL_BYTES else None)
        content['files'].append({'module': entry['module'], 'name': entry['name'], 'version': entry['label'], 'bytes': entry['bytes'],
                                 'checksum': entry['checksum'], 'problem': problem})
        if problem:
            content['status'] = 'refused'
    # Result 4: applied history (immutability of applied versions, ordering of new ones).
    if history is None:
        history_result = {'status': 'unknown', 'note': 'applied history not read; unknown is not approval', 'pending': [], 'applied': {}}
    else:
        require(isinstance(history, list) and all(isinstance(r, dict) and {'module', 'version', 'checksum'} <= set(r) for r in history),
                'History rows require module, version and checksum')
        modules = sorted({loc['module'] for loc in locations if loc['vendor'] == config['target_vendor']})
        applied = {module: {r['version']: r for r in history if r['module'] == module} for module in modules}
        foreign = sorted({r['module'] for r in history} - set(modules))
        by_key = {(f['module'], f['label']): f for f in target}
        problems, pending = [], []
        for module in modules:
            for label, row in sorted(applied[module].items(), key=lambda kv: [int(p) for p in kv[0].split('.')]):
                entry = by_key.get((module, label))
                if entry is None:
                    problems.append({'module': module, 'version': label, 'problem': 'applied version has no file; immutability cannot be verified'})
                elif entry['checksum'] != row['checksum']:
                    problems.append({'module': module, 'version': label, 'problem': 'applied version modified', 'file': entry['name'],
                                     'applied_checksum': row['checksum'], 'file_checksum': entry['checksum']})
            max_applied = max((f['version'] for f in target if f['module'] == module and f['label'] in applied[module]), default=None)
            for entry in (f for f in target if f['module'] == module):
                if entry['label'] in applied[module]:
                    continue
                if max_applied is not None and entry['version'] < max_applied:
                    problems.append({'module': module, 'version': entry['label'], 'problem': 'out of order: lower than an applied version', 'file': entry['name']})
                else:
                    pending.append({'module': module, 'version': entry['label'], 'name': entry['name']})
        history_result = {'status': 'refused' if problems else 'ok',
                          'applied': {module: sorted(rows, key=lambda s: [int(p) for p in s.split('.')]) for module, rows in applied.items()},
                          'pending': pending, 'problems': problems, 'foreign_modules': foreign,
                          'note': 'history is per module; rows of modules outside this config are listed, never judged'}
    # Result 5: the live schema (observed tables versus the tables the config expects).
    if live_tables is None:
        schema = {'status': 'unknown', 'note': 'live schema not observed; unknown is not approval', 'expected': config['expected_tables']}
    else:
        require(isinstance(live_tables, list) and all(type(t) is str for t in live_tables), 'Live tables must be names')
        missing = sorted(set(config['expected_tables']) - set(live_tables))
        schema = {'status': 'refused' if missing else 'ok', 'expected': config['expected_tables'], 'observed': sorted(live_tables), 'missing': missing}
    location_status = 'refused' if any(loc['status'] == 'refused' for loc in locations) else 'ok'
    results = {'locations': location_status, 'filenames': filenames['status'], 'parity': parity['status'], 'content': content['status'],
               'history': history_result['status'], 'schema': schema['status']}
    allowed = all(status in {'ok', 'not_applicable'} for status in results.values())
    return {'tool': TOOL, 'config_hash': config['config_hash'], 'target_vendor': config['target_vendor'], 'results': results,
            'apply_allowed': allowed, 'pending': history_result.get('pending', []) if allowed else [],
            'locations': locations, 'filenames': filenames, 'parity': parity, 'content': content, 'history': history_result, 'schema': schema,
            'denominator': {'locations_configured': len(locations), 'locations_required': sum(loc['required'] for loc in locations),
                            'locations_found': sum(loc['state'] == 'found' for loc in locations),
                            'files_supported': sum(len(loc['files']) for loc in locations),
                            'files_refused': sum(len(loc['refused_names']) for loc in locations),
                            'files_ignored': sum(len(loc['ignored']) for loc in locations)},
            'note': 'MAX+1 guidance does not prevent collisions; a new version is reconciled against the history read under the lock at apply time'}
