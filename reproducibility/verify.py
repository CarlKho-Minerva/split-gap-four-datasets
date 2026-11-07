"""Verify the candidate's toolkit-generated artifacts and source dependencies.

Use --data to additionally hash the original dataset archives before reproduction.
This is an integrity check, not independent validation of the statistical method.
"""
import argparse
import hashlib
import json
from pathlib import Path


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def verify(root, data=False):
    manifest = json.loads((root/'results/manifest.json').read_text())
    for name, digest in manifest['files'].items():
        assert sha(root/name) == digest, f'Artifact mismatch: {name}'
    assert sha(root/'analysis/analysis.py') == manifest['script_sha256'], 'Main script changed'
    assert sha(root/'analysis/config.json') == manifest['config_sha256'], 'Configuration changed'
    dependencies = json.loads((root/'results/reproducibility_manifest.json').read_text())
    for name, digest in dependencies['sources'].items():
        assert sha(root/name) == digest, f'Source/dependency mismatch: {name}'
    numbers = json.loads((root/'results/results.json').read_text())['numbers']
    stable = json.loads((root/'results/stable_numbers.json').read_text())['numbers']
    assert numbers == stable, 'Stable numeric export differs from toolkit results'
    if data:
        provenance = json.loads((root/'provenance.json').read_text())
        for name, digest in provenance['files'].items():
            assert sha(root/'data/raw'/name) == digest, f'Archive mismatch: {name}'
    return len(manifest['files']), len(dependencies['sources'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', action='store_true')
    args = parser.parse_args()
    artifacts, sources = verify(Path(__file__).resolve().parent.parent, args.data)
    print(f'Integrity check passed: {artifacts} artifacts and {sources} source/dependency files.')
