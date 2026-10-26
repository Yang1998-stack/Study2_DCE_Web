import { Unzip, UnzipInflate } from 'fflate';
import { XMLParser } from 'fast-xml-parser';
import { assert } from './security';
import { all, stmt } from './db';
import type { Row } from './types';
export function base64(bytes:Uint8Array) {let s='';for(let i=0;i<bytes.length;i+=16384)s+=String.fromCharCode(...bytes.subarray(i,i+16384));return btoa(s)}
export function unbase64(s:string) {assert(typeof s==='string'&&/^[A-Za-z0-9+/]*={0,2}$/.test(s)&&s.length%4===0,'文件编码不合法');return Uint8Array.from(atob(s),c=>c.charCodeAt(0))}
export function archiveStatements(db:D1Database,id:string,filename:string,raw:Uint8Array){const out=[];for(let i=0;i<raw.length;i+=400000)out.push(stmt(db,'INSERT INTO archive_chunks(archive_id,filename,part,data_base64) VALUES (?,?,?,?)',id,filename,i/400000,base64(raw.subarray(i,i+400000))));return out}
export async function archiveFiles(db:D1Database,id:string) {const rows=await all(db,'SELECT * FROM archive_chunks WHERE archive_id=? ORDER BY filename,part',id),groups=new Map<string,Uint8Array[]>();for(const r of rows){const a=groups.get(r.filename)||[];a.push(unbase64(r.data_base64));groups.set(r.filename,a)}return Object.fromEntries([...groups].map(([n,a])=>{const b=new Uint8Array(a.reduce((s,x)=>s+x.length,0));let offset=0;for(const x of a){b.set(x,offset);offset+=x.length}return[n,b]}))}
function parseCSV(text:string) {
  const rows:string[][]=[],row:string[]=[];let cell='',quoted=false;
  for(let i=0;i<text.length;i++){const c=text[i];if(quoted){if(c==='"'&&text[i+1]==='"'){cell+='"';i++}else if(c==='"')quoted=false;else cell+=c}else if(c==='"'){assert(cell==='','CSV引号格式错误');quoted=true}else if(c===','){row.push(cell);cell=''}else if(c==='\n'||c==='\r'){if(c==='\r'&&text[i+1]==='\n')i++;row.push(cell);if(row.some(x=>x!==''))rows.push([...row]);row.length=0;cell=''}else cell+=c;assert(rows.length<=20001&&cell.length<=100000,'CSV行数或单元格过大')}
  assert(!quoted,'CSV引号没有闭合');if(cell!==''||row.length){row.push(cell);rows.push(row)}return rows;
}
function unzipLimited(raw:Uint8Array){
  const files:Record<string,Uint8Array>={};let total=0,count=0;
  const unzip=new Unzip(file=>{assert(++count<=300,'XLSX压缩包文件数过多');assert(file.name.length<200&&!file.name.includes('..'),'XLSX文件路径不合法');const pieces:Uint8Array[]=[];let size=0;file.ondata=(err,chunk,final)=>{assert(!err,'XLSX解压失败');size+=chunk.length;total+=chunk.length;if(total>32*1024*1024){file.terminate();throw new Error('XLSX解压内容超过32 MiB')}pieces.push(chunk);if(final){const b=new Uint8Array(size);let offset=0;for(const c of pieces){b.set(c,offset);offset+=c.length}files[file.name]=b}};file.start()});unzip.register(UnzipInflate);unzip.push(raw,true);return files;
}
const array=(v:any)=>v===undefined?[]:Array.isArray(v)?v:[v];
function parseXLSX(raw:Uint8Array){
  const files=unzipLimited(raw),parser=new XMLParser({ignoreAttributes:false,parseTagValue:false,processEntities:true});
  const xml=(name:string)=>{assert(files[name],'XLSX缺少'+name);const s=new TextDecoder('utf-8',{fatal:true,ignoreBOM:false}).decode(files[name]);assert(!/<!DOCTYPE|<!ENTITY/i.test(s),'XLSX不允许DTD或实体声明');return parser.parse(s)};
  const sst=files['xl/sharedStrings.xml']?array(xml('xl/sharedStrings.xml').sst?.si).map(si=>typeof si.t==='string'?si.t:array(si.r).map(r=>r.t??'').join('')):[];
  const paths=Object.keys(files).filter(k=>/^xl\/worksheets\/sheet\d+\.xml$/.test(k)).sort();assert(paths.length===1,'XLSX每个文件仅支持一个工作表，请分别保存各张数据表');
  const rows:string[][]=[];
  for(const r of array(xml(paths[0]).worksheet?.sheetData?.row)){
    const row:string[]=[];for(const c of array(r.c)){assert(c.f===undefined,'XLSX不允许公式，不能采用缓存计算结果');const col=String(c['@_r']||'').match(/^[A-Z]+/)?.[0];assert(col,'XLSX列引用错误');let index=0;for(const a of col)index=index*26+a.charCodeAt(0)-64;assert(index<=100,'列数超过100');const value=c['@_t']==='s'?sst[Number(c.v)]:c['@_t']==='inlineStr'?c.is?.t:c.v;row[index-1]=String(value??'')}
    if(row.some(x=>x!==''))rows.push(row);assert(rows.length<=20001,'记录数超过20000');
  }return rows;
}
export function readTable(name:string,raw:Uint8Array,maxFields=100){
  assert(raw.byteLength<=8*1024*1024,'单文件超过8 MiB');
  const table=name.endsWith('.csv')?parseCSV(new TextDecoder('utf-8',{fatal:true,ignoreBOM:false}).decode(raw).replace(/^\ufeff/,'')):parseXLSX(raw);
  assert(table.length>0,'文件为空');const fields=table[0].map(x=>String(x??'').trim());
  assert(fields.length>0&&fields.length<=maxFields&&new Set(fields).size===fields.length&&fields.every(x=>x&&/^[A-Za-z_][A-Za-z0-9_]*$/.test(x)),'字段名称为空、重复或格式不合法');
  const rows=table.slice(1).map(r=>{assert(r.length<=fields.length,'记录列数超过表头');return Object.fromEntries(fields.map((f,i)=>{const s=r[i]??'';assert(!/^[=+@]/.test(s),'文件含公式型单元格');return[f,s]}))});
  return {fields,rows};
}
