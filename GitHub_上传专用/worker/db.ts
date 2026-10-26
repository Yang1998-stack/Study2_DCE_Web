import schema from '../migrations/0001_initial.sql';
import { designs } from './data';
import { assert } from './security';
import type { Env, Row } from './types';
export const stmt = (db:D1Database,sql:string,...params:any[]) => db.prepare(sql).bind(...params.map(p=>p===undefined?null:p));
export async function one<T=Row>(db:D1Database,sql:string,...params:any[]):Promise<T|null> { return stmt(db,sql,...params).first<T>() }
export async function all<T=Row>(db:D1Database,sql:string,...params:any[]):Promise<T[]> { return (await stmt(db,sql,...params).all<T>()).results }
export async function run(db:D1Database,sql:string,...params:any[]) { return stmt(db,sql,...params).run() }
export async function initialize(env:Env) {
  assert(env.DB, 'D1尚未绑定，请将数据库绑定为DB', 503);
  const exists=await one(env.DB,"SELECT name FROM sqlite_master WHERE type='table' AND name='study_meta'");
  if (!exists) await env.DB.batch(schema.split('-- statement-breakpoint').filter(s=>s.trim()).map(s=>env.DB.prepare(s)));
  await env.DB.batch([
    stmt(env.DB,"INSERT OR IGNORE INTO study_meta(key,value) VALUES ('instance_id',?)",crypto.randomUUID()),
    stmt(env.DB,"INSERT OR IGNORE INTO study_meta(key,value) VALUES ('schema_version','workers-d1-v1')"),
    ...Object.values(designs).map(d=>stmt(env.DB,'INSERT OR IGNORE INTO designs(version,task_hash,tasks_json) VALUES (?,?,?)',d.config.version,d.config.task_sha256,JSON.stringify(d.tasks)))
  ]);
  const saved=await all(env.DB,'SELECT version,task_hash FROM designs');
  for (const d of Object.values(designs)) assert(saved.some(r=>r.version===d.config.version&&r.task_hash===d.config.task_sha256),'同一设计版本的题库已改变，拒绝启动',503);
}
export async function instance(db:D1Database) { return (await one(db,"SELECT value FROM study_meta WHERE key='instance_id'"))!.value as string }
export function bulk(db:D1Database,table:string,columns:string[],rows:Row[],guard?:{batch:string}) {
  const chunks:Row[][]=[];let current:Row[]=[];let size=0;
  for (const r of rows) {const bytes=new TextEncoder().encode(JSON.stringify(r)).length; if(size+bytes>220000&&current.length){chunks.push(current);current=[];size=0}current.push(r);size+=bytes}
  if(current.length)chunks.push(current);
  return chunks.map(chunk=>stmt(db,`INSERT OR IGNORE INTO ${table} (${columns.join(',')}) SELECT ${columns.map(c=>`json_extract(value,'$.${c}')`).join(',')} FROM json_each(?)${guard?" WHERE EXISTS(SELECT 1 FROM import_batches WHERE id=? AND status='previewed')":''}`,JSON.stringify(chunk),...(guard?[guard.batch]:[])));
}
