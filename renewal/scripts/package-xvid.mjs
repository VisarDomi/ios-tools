// Relocate the already-delivered runtime; no provider/auth/UI changes.
import { readFileSync, writeFileSync, mkdirSync, copyFileSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';

export function packageXvid(destination) {
    const source=resolve(dirname(fileURLToPath(import.meta.url)),'../dist/stream-viewer-extension');
    const manifest=JSON.parse(readFileSync(resolve(source,'manifest.json'),'utf8'));
    const matches=['https://xvideos.com/*','https://www.xvideos.com/*'];
    manifest.name='Xvid';
    manifest.description='The existing Stream Viewer for XVideos, hosted by Tango.';
    manifest.host_permissions=matches;
    for(const content of manifest.content_scripts) content.matches=matches;
    mkdirSync(destination,{recursive:true});
    copyFileSync(resolve(source,'content.js'),resolve(destination,'content.js'));
    writeFileSync(resolve(destination,'manifest.json'),JSON.stringify(manifest,null,2)+'\n');
    const hash=createHash('sha256').update(readFileSync(resolve(destination,'content.js'))).digest('hex');
    console.log('Packaged the delivered Xvid runtime unchanged: '+hash);
}
