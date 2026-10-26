import {readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import assert from 'node:assert/strict';
const read=p=>readFileSync(new URL('../../'+p,import.meta.url));
const sha=bytes=>createHash('sha256').update(bytes).digest('hex');
for(const path of ['config/design_config.json','designs/legacy_v1_config.json']){
 const cfg=JSON.parse(read(path));const raw=read(cfg.task_file);assert.equal(sha(raw),cfg.task_sha256,'题库文件哈希必须保持不变');
 const tasks=JSON.parse(raw);assert.equal(tasks.length,16);for(const b of ['A','B'])assert.equal(tasks.filter(t=>t.block===b).length,8);
 for(const t of tasks)for(const o of [t.a,t.b])for(const [k,v]of Object.entries(cfg.levels))assert(v.includes(o[k]));
}
const expected={chart:'21292f60ad8ab7d4120a73fde93d6050728768c82ac2bc06dc2bfd56614f445f',nature:'6dfe23fb124ccd4912cc3ee35c7519bd9975d2da3b6a6c270bfba73961ef2148'};
for(const [name,hash]of Object.entries(expected))assert.equal(sha(read('static/stimuli/'+name+'.jpg')),hash,'广告刺激物不能修改');
const cfg=JSON.parse(read('wrangler.jsonc'));assert.equal(cfg.name,'study2-dce-web');assert.equal(cfg.vars.QUICKFORM_FORMAL_ENABLED,'NO');assert.equal(cfg.vars.DCE_MODE,'demo');assert.equal(cfg.assets.directory,'./static');
assert(!Object.keys(cfg.vars).some(k=>/PASSWORD|TOKEN|SECRET/.test(k)),'凭据不得进入Wrangler明文配置');
console.log('原始16题、双区组、属性水平、两张广告哈希及正式同步禁用检查通过。');
