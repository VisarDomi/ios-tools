import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync, readFileSync, rmSync, mkdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { selectedReaders, stageBundle, inspectBundle } from '../scripts/suite.mjs';

test('selection rejects typos before building and deduplicates a requested reader', () => {
    assert.equal(selectedReaders([]).length, 4);
    assert.deepEqual(selectedReaders(['manga-reader', 'manga-reader']), ['manga-reader']);
    assert.throws(() => selectedReaders(['manga-readre']), /Unknown reader/);
});

test('stages a complete bundle without modifying another extension; incomplete replacement preserves old files', () => {
    const temp = mkdtempSync(join(tmpdir(), 'reader-packaging-'));
    try {
        const source = join(temp, 'source');
        const target = join(temp, 'manga-reader-extension');
        const other = join(temp, 'gallery-reader-extension');
        for (const directory of [source, other]) mkdirSync(directory);
        writeFileSync(join(other, 'content.js'), 'other reader');
        writeFileSync(join(source, 'manifest.json'), JSON.stringify({ content_scripts: [{ js: ['content.js'] }] }));
        writeFileSync(join(source, 'content.js'), 'reader v1');
        const files = ['manifest.json', 'content.js'];
        const hashes = stageBundle(source, target, files);
        assert.deepEqual(inspectBundle(target, files), hashes);
        assert.equal(readFileSync(join(other, 'content.js'), 'utf8'), 'other reader');
        writeFileSync(join(source, 'manifest.json'), JSON.stringify({ content_scripts: [{ js: ['missing.js'] }] }));
        writeFileSync(join(source, 'content.js'), 'reader v2');
        assert.throws(() => stageBundle(source, target, files), /unstaged file/);
        assert.deepEqual(inspectBundle(target, files), hashes);
    } finally { rmSync(temp, { recursive: true, force: true }); }
});

test('requires the Gallery rule file referenced by the manifest', () => {
    const temp = mkdtempSync(join(tmpdir(), 'reader-packaging-'));
    try {
        writeFileSync(join(temp, 'manifest.json'), JSON.stringify({ content_scripts: [{ js: ['content.js'] }], declarative_net_request: { rule_resources: [{ path: 'rules.json' }] } }));
        writeFileSync(join(temp, 'content.js'), 'gallery reader');
        assert.throws(() => inspectBundle(temp, ['manifest.json', 'content.js']), /rules.json/);
        writeFileSync(join(temp, 'rules.json'), '[]');
        assert.equal(Object.keys(inspectBundle(temp, ['manifest.json', 'content.js', 'rules.json'])).length, 3);
    } finally { rmSync(temp, { recursive: true, force: true }); }
});
