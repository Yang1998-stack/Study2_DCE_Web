import { active, designs } from './data';
import { one, run, stmt } from './db';
import { assert, cookie, cookieHeader, digest, equal, json, modeOf, now, seconds, token } from './security';
import type { Env, Row } from './types';
export const configured=(env:Env)=>!!env.ADMIN_USERNAME&&!!env.ADMIN_PASSWORD&&env.ADMIN_PASSWORD.length>=12;
export const fingerprint=(env:Env)=>digest(JSON.stringify([env.ADMIN_USERNAME,env.ADMIN_PASSWORD]));
export async function admin(request:Request,env:Env,csrf=false){
  const value=cookie(request,'dce_admin');if(!value||!configured(env))return null;
  const row=await one(env.DB,'SELECT * FROM admin_sessions WHERE digest=? AND expires>?',await digest(value),now());
  if(!row||!equal(row.credential_fingerprint,await fingerprint(env))||csrf&&!equal(request.headers.get('X-CSRF-Token')||'',row.csrf))return null;
  return row;
}
export function session(env:Env,a:Row|null){return {authenticated:!!a,configured:configured(env),csrf:a?.csrf??null,mode:modeOf(env),design_version:active.config.version,design_versions:Object.keys(designs),platform:'cloudflare-workers'}}
export async function login(request:Request,env:Env,data:Row){
  assert(configured(env),'后台尚未配置，请在Cloudflare Secrets设置ADMIN_USERNAME和至少12字符的ADMIN_PASSWORD',503);
  assert(typeof data.username==='string'&&typeof data.password==='string'&&data.username.length<=100&&data.password.length<=1000,'账号密码格式错误');
  const key=await digest(request.headers.get('CF-Connecting-IP')||'local'),stamp=now();
  const fail=await one(env.DB,'SELECT * FROM auth_failures WHERE key=?',key);
  assert(!fail||seconds(fail.window_at,stamp)!>=900||fail.attempts<8,'尝试次数过多，请15分钟后重试',429);
  const good=equal(await digest(data.username),await digest(env.ADMIN_USERNAME!))&&equal(await digest(data.password),await digest(env.ADMIN_PASSWORD!));
  if(!good){await run(env.DB,`INSERT INTO auth_failures(key,window_at,attempts) VALUES (?,?,1) ON CONFLICT(key) DO UPDATE SET attempts=CASE WHEN window_at<? THEN 1 ELSE attempts+1 END,window_at=CASE WHEN window_at<? THEN excluded.window_at ELSE window_at END`,key,stamp,new Date(Date.now()-900000).toISOString(),new Date(Date.now()-900000).toISOString());return json({error:'账号或密码错误'},401)}
  const value=token(),csrf=token(),expires=new Date(Date.now()+28800000).toISOString();
  await env.DB.batch([stmt(env.DB,'DELETE FROM auth_failures WHERE key=?',key),stmt(env.DB,'DELETE FROM admin_sessions WHERE expires<=?',stamp),stmt(env.DB,'INSERT INTO admin_sessions(digest,csrf,expires,credential_fingerprint) VALUES (?,?,?,?)',await digest(value),csrf,expires,await fingerprint(env))]);
  return json(session(env,{csrf}),200,cookieHeader(request,'dce_admin',value,28800));
}
export async function participant(request:Request,env:Env){const value=cookie(request,'dce_session');return value?one(env.DB,'SELECT * FROM participants WHERE token_digest=? AND mode=?',await digest(value),modeOf(env)):null}
