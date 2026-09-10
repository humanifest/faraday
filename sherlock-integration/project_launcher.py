#!/usr/bin/env python3
"""Project-owned entry point for an explicitly pinned, offline Sherlock runtime."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tempfile
import os
import zipfile


DEPENDENCIES = frozenset({'jsonschema', 'referencing', 'attrs', 'jsonschema-specifications', 'rpds-py', 'pypdf'})
OWNED_PACKAGES = frozenset({'sherlock', 'rigour_core', 'sherlock_schema_data'})
INSTALL_METADATA = frozenset({'INSTALLER', 'REQUESTED', 'direct_url.json', 'RECORD'})


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def verify_runtime(runtime, wheel):
    """Inspect bytes and inventory using stdlib only, before importing the engine."""
    if runtime.is_symlink() or runtime.parent.is_symlink() or not runtime.is_dir():
        raise ValueError('Pinned runtime must be a real local directory; run setup for this wheel.')
    with zipfile.ZipFile(wheel) as archive:
        entries = {}
        for item in archive.infolist():
            if item.is_dir():
                continue
            parts = PurePosixPath(item.filename).parts
            if (not parts or PurePosixPath(item.filename).is_absolute() or '..' in parts
                    or '\\' in item.filename or item.filename in entries
                    or (item.external_attr >> 16) & 0o170000 == 0o120000):
                raise ValueError('Pinned wheel has an unsafe or duplicate member')
            entries[item.filename] = archive.read(item)
    metadata_roots = {PurePosixPath(name).parts[0] for name in entries if PurePosixPath(name).parts[0].endswith('.dist-info')}
    if len(metadata_roots) != 1 or not all(any(name.startswith(package + '/') for name in entries) for package in OWNED_PACKAGES):
        raise ValueError('Pinned wheel does not contain the complete expected Sherlock package inventory')
    allowed_roots = OWNED_PACKAGES | metadata_roots
    if any(PurePosixPath(name).parts[0] not in allowed_roots for name in entries):
        raise ValueError('Pinned wheel contains an unsupported top-level payload')
    actual = set()
    for path in runtime.rglob('*'):
        relative = path.relative_to(runtime).as_posix()
        parts = PurePosixPath(relative).parts
        if path.is_symlink():
            raise ValueError('Pinned runtime contains a symbolic link: ' + relative)
        if parts[0] not in allowed_roots or '__pycache__' in parts or path.suffix in {'.pyc', '.pyo'}:
            raise ValueError('Pinned runtime contains an unexpected executable or importable path: ' + relative)
        if path.is_dir():
            if parts[0] in OWNED_PACKAGES and not any(name.startswith(relative + '/') for name in entries):
                raise ValueError('Pinned runtime contains an extra package directory: ' + relative)
            continue
        if not path.is_file():
            raise ValueError('Pinned runtime contains a nonregular file: ' + relative)
        generated_metadata = len(parts) == 2 and parts[0] in metadata_roots and parts[1] in INSTALL_METADATA
        if relative not in entries and not generated_metadata:
            raise ValueError('Pinned runtime contains an unexpected file: ' + relative)
        if relative in entries and not generated_metadata and path.read_bytes() != entries[relative]:
            raise ValueError('Installed runtime differs from the pinned wheel: ' + relative)
        actual.add(relative)
    missing = set(entries) - actual
    if missing:
        raise ValueError('Installed runtime is missing pinned files: ' + ', '.join(sorted(missing)))


def verify_environment(runtime, lock):
    expected = lock.get('dependency_versions')
    if not isinstance(expected, dict) or set(expected) != DEPENDENCIES or any(not isinstance(value, str) or not value for value in expected.values()):
        raise ValueError('Runtime lock must pin every supported dependency version explicitly')
    if not isinstance(lock.get('python_version'), str) or not lock['python_version']:
        raise ValueError('Runtime lock must pin the Python version explicitly')
    # Metadata inspection executes no Sherlock or dependency module. -I ignores
    # user-site/PYTHONPATH; exact versions describe the environment actually used.
    code = ('import importlib.metadata as m,json,platform,sys; '
            'sys.path.insert(0,sys.argv[1]); versions={}; '
            'exec("for name in json.loads(sys.argv[2]):\\n try: versions[name]=m.version(name)\\n except m.PackageNotFoundError: versions[name]=None"); '
            'print(json.dumps({"python":platform.python_version(),"dependencies":versions,"sherlock":m.version("sherlock-investigation")}))')
    observed = json.loads(subprocess.check_output([sys.executable, '-I', '-B', '-c', code, str(runtime), json.dumps(sorted(DEPENDENCIES))], text=True))
    mismatches = []
    if observed['python'] != lock['python_version']:
        mismatches.append('Python requires ' + lock['python_version'] + ', found ' + observed['python'])
    if observed['sherlock'] != lock['version']:
        mismatches.append('Sherlock version differs from the runtime lock')
    for name, version in expected.items():
        if observed['dependencies'][name] != version:
            mismatches.append(name + ' requires ' + version + ', found ' + str(observed['dependencies'][name]))
    if mismatches:
        raise ValueError('Pinned runtime environment mismatch: ' + '; '.join(mismatches) + '. Select the reviewed Python environment or update the lock explicitly; no host dependencies were installed.')


def main():
    arguments = sys.argv[1:]
    if any(argument.startswith('--') and any(option.startswith(argument.split('=', 1)[0])
           for option in ('--config', '--runtime-lock')) for argument in arguments):
        raise ValueError('Project config and runtime lock are fixed by this launcher and cannot be overridden')
    base = Path(__file__).resolve().parent
    lock = json.loads((base / 'runtime-lock.json').read_text())
    wheel = Path(lock['wheel_path']).expanduser().resolve()
    expected = lock['wheel_sha256']
    if not wheel.is_file() or digest(wheel) != expected:
        raise ValueError('Pinned Sherlock wheel is missing or changed; verify and update the runtime lock explicitly.')
    runtime = base / '.runtime' / expected
    if arguments[:1] == ['setup']:
        if runtime.is_symlink() or runtime.parent.is_symlink():
            raise ValueError('Pinned runtime directory cannot be a symbolic link')
        if not runtime.exists():
            runtime.parent.mkdir(exist_ok=True)
            with tempfile.TemporaryDirectory(prefix='install-', dir=runtime.parent) as temporary:
                target = Path(temporary) / 'package'
                subprocess.run([sys.executable, '-I', '-B', '-m', 'pip', 'install', '--no-index', '--no-deps', '--no-compile',
                                '--disable-pip-version-check', '--target', str(target), str(wheel)], check=True)
                # The project launcher is the only entry point. Pip's generated
                # console wrappers are unused and are outside wheel inventory.
                if (target / 'bin').exists():
                    shutil.rmtree(target / 'bin')
                verify_runtime(target, wheel)
                verify_environment(target, lock)
                os.rename(target, runtime)
        arguments = ['doctor']
    elif not runtime.is_dir():
        raise ValueError('Run this project launcher with setup once; it installs only the pinned local wheel.')
    verify_runtime(runtime, wheel)
    verify_environment(runtime, lock)
    code = 'import sys; sys.path.insert(0, sys.argv.pop(1)); from sherlock.consumer import main; raise SystemExit(main())'
    return subprocess.call([sys.executable, '-I', '-B', '-c', code, str(runtime),
                            '--config', str(base / 'project.json'), '--runtime-lock', str(base / 'runtime-lock.json'), *arguments])


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, OSError, KeyError, subprocess.CalledProcessError, zipfile.BadZipFile) as exc:
        print(json.dumps({'ok': False, 'error': str(exc)}), file=sys.stderr)
        raise SystemExit(2)
