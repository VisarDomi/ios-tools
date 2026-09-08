// Packaging only. Provider/runtime/manifest generation stays in each source repo.
import { execFileSync } from 'node:child_process';
import { copyFileSync, mkdirSync, readFileSync, existsSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const root = fileURLToPath(new URL('../', import.meta.url));
export const readers = {
    'gallery-reader': { path: '../manga/gallery-reader', files: ['manifest.json', 'content.js', 'rules.json'], product: 'Gallery Reader Extension Extension.appex', id: 'Extension' },
    'km-explorer': { path: '../video/km-explorer', files: ['manifest.json', 'content.js'], product: 'KM Explorer.appex', id: 'KMExplorer' },
    'stream-viewer': { path: '../video/stream-viewer', files: ['manifest.json', 'content.js'], product: 'Stream Viewer.appex', id: 'StreamViewer' },
    'manga-reader': { path: '../manga/manga-reader', files: ['manifest.json', 'content.js'], product: 'Manga Reader.appex', id: 'MangaReader' },
};

export function selectedReaders(names) {
    const selected = names.length ? names : Object.keys(readers);
    for (const name of selected) if (!Object.hasOwn(readers, name)) throw new Error(`Unknown reader: ${name}`);
    return [...new Set(selected)];
}

export function inspectBundle(directory, files) {
    // Read/validate the whole bundle before overwriting any staged file.
    const content = new Map(files.map(file => [file, readFileSync(resolve(directory, file))]));
    const manifest = JSON.parse(content.get('manifest.json').toString());
    for (const file of [
        ...manifest.content_scripts.flatMap(script => script.js),
        ...(manifest.declarative_net_request?.rule_resources ?? []).map(rule => rule.path),
    ]) {
        if (!content.has(file)) throw new Error(`Manifest references unstaged file: ${file}`);
    }
    return Object.fromEntries([...content].map(([file, bytes]) => [file, createHash('sha256').update(bytes).digest('hex')]));
}

export function stageBundle(source, target, files) {
    const hashes = inspectBundle(source, files);
    mkdirSync(target, { recursive: true });
    for (const file of files) copyFileSync(resolve(source, file), resolve(target, file));
    return hashes;
}

export function verifyStaged() {
    return Object.fromEntries(Object.entries(readers).map(([name, reader]) => [
        name, inspectBundle(resolve(root, 'dist', `${name}-extension`), reader.files),
    ]));
}

function main() {
    const [mode, ...args] = process.argv.slice(2);
    if (!['build', 'stage', 'verify'].includes(mode)) throw new Error('Use build|stage|verify [reader names]');
    if (mode === 'verify') {
        if (args.length) throw new Error('verify checks the complete four-extension suite');
        console.log(JSON.stringify(verifyStaged(), null, 2));
        return;
    }
    const overridesFile = resolve(root, 'readers.local.json');
    const overrides = existsSync(overridesFile) ? JSON.parse(readFileSync(overridesFile, 'utf8')) : {};
    for (const name of selectedReaders(args)) {
        const reader = readers[name];
        const repo = resolve(root, overrides[name] ?? reader.path);
        if (mode === 'build') execFileSync(process.execPath, ['scripts/build-extension.mjs'], { cwd: repo, stdio: 'inherit' });
        const hashes = stageBundle(resolve(repo, 'dist/extension'), resolve(root, 'dist', `${name}-extension`), reader.files);
        console.log(`${name}: staged ${Object.keys(hashes).length} private files`);
    }
    console.log('Private artifacts only; do not publish dist or the signed app. Unselected bundles were not changed.');
}

if (process.argv[1] && pathToFileURL(resolve(process.argv[1])).href === import.meta.url) main();
