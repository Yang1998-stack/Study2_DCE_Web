"""Validate exported QuickForm CSV/JSON, then restore 24 alternative rows/person."""
import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
import storage as s
import quickform_payload as qm
import design_registry as registry

def read_records(path):
    if path.suffix.lower()=='.csv':
        with path.open(encoding='utf-8-sig',newline='') as f: raw=list(csv.DictReader(f))
    elif path.suffix.lower()=='.json':
        raw=json.loads(path.read_text(encoding='utf-8-sig'))
        if isinstance(raw,dict):raw=raw.get('submissions',[raw])
    else: raise ValueError('仅支持QuickForm导出的UTF-8 CSV或JSON')
    if not isinstance(raw,list): raise ValueError('导出记录须为数组')
    result=[]
    for item in raw:
        if not isinstance(item,dict): raise ValueError('导出记录不是对象')
        if 'payload_version' not in item and 'data' in item:
            item=json.loads(item['data']) if isinstance(item['data'],str) else item['data']
        result.append(item)
    return result

def main():
    p=argparse.ArgumentParser(description='从QuickForm导出数据还原DCE长格式，不生成或补齐选择')
    p.add_argument('file',type=Path);p.add_argument('--mode',required=True,choices=s.MODES);p.add_argument('--output-dir',type=Path,required=True)
    p.add_argument('--design-version',default=s.VERSION,choices=list(registry.DESIGNS))
    args=p.parse_args(); records=read_records(args.file); rows=[];seen=set()
    for index,record in enumerate(records,1):
        try:
            if record.get('design_version')!=args.design_version:raise ValueError('必须明确选择同一设计版本，不能把历史和新版合并还原')
            restored=qm.restore_long(record,args.mode)
            pid=record['participant_id']
            if pid in seen: raise ValueError('同一全局UUID重复，请先人工核查远端重复；不自动删行或覆盖')
            seen.add(pid);rows.extend(restored)
        except (ValueError,TypeError,KeyError) as exc:raise SystemExit(f'第{index}条记录无效：{exc}')
    columns=['participant_id','choice_set_id','alternative_id','chosen','origin','environmental_verification','quality_information','price','opt_out','visual_type','ai_disclosure','dce_block','design_version','survey_mode','task_id','position','swapped','started_at','answered_at','local_participant_id','source_instance','price_yuan','price_level','product_volume_ml']
    target=args.output_dir/'choice_long.csv'
    if target.exists(): raise SystemExit('输出文件已存在，请使用新的输出目录，不覆盖已有分析数据')
    args.output_dir.mkdir(parents=True,exist_ok=True)
    target.write_bytes(s.csv_bytes(columns,rows))
    (args.output_dir/'restoration_manifest.json').write_text(json.dumps(dict(restored_at=s.now(),source_file=args.file.name,source_sha256=s.digest(args.file.read_bytes()),mode=args.mode,design_version=args.design_version,participants=len(seen),rows=len(rows),note='仅展开原选择；N的属性及价格为空'),ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'已还原{len(seen)}名参与者、{len(rows)}行：{target}')

if __name__=='__main__': main()
