import {spawnSync} from 'node:child_process';
if(!process.env.npm_execpath)throw Error('请使用 npm run ci 启动检查');
for(const script of ['test','build']){
  const result=spawnSync(process.execPath,[process.env.npm_execpath,'run',script],{stdio:'inherit',env:process.env});
  if(result.error)throw result.error;
  if(result.status!==0)process.exit(result.status||1);
}
