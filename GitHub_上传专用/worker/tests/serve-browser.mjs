import {build} from 'esbuild';
import {Miniflare,createFetchMock} from 'miniflare';
import {resolve} from 'node:path';
import {randomUUID} from 'node:crypto';
await build({entryPoints:['worker/index.ts'],bundle:true,format:'esm',platform:'browser',loader:{'.sql':'text'},outfile:'.worker-build/browser.mjs'});
const mock=createFetchMock();mock.disableNetConnect();
const mf=new Miniflare({host:'127.0.0.1',port:8788,modules:true,scriptPath:resolve('.worker-build/browser.mjs'),compatibilityDate:'2026-07-01',assets:{directory:resolve('static'),binding:'ASSETS',routerConfig:{has_user_worker:true,invoke_user_worker_ahead_of_assets:true},assetConfig:{html_handling:'none',not_found_handling:'none'}},d1Databases:{DB:'browser-test'},d1Persist:resolve('.wrangler/browser/'+randomUUID()),bindings:{DCE_MODE:'demo',ADMIN_USERNAME:'researcher',ADMIN_PASSWORD:'local-test-password-never-production'},fetchMock:mock});
console.log('Browser test only:',String(await mf.ready));
async function stop(){await mf.dispose();process.exit(0)}process.on('SIGINT',stop);process.on('SIGTERM',stop);
