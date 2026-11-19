"""Index existing full-length review packets and record human decisions.

No simulation, model, or automatic visual approval. The offline HTML exports
annotations; checking an export does not change the dataset selection.
"""
import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from urllib.parse import quote

from prepare_sft_data import ROOT, digest, read_json, write_new


PAGE = r'''<!doctype html>
<html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>抽屉示教数据验收</title>
<style>
:root{color-scheme:dark;font:16px system-ui,"Microsoft YaHei","PingFang SC",sans-serif;background:#0b1220;color:#e2e8f0}
body{max-width:1180px;margin:36px auto;padding:0 20px}h1{margin-bottom:8px}
p{line-height:1.6;color:#b9c6db}a{color:#93c5fd}code{font-size:12px;overflow-wrap:anywhere}
section{background:#111e32;border:1px solid #2b405d;border-radius:14px;padding:22px;margin:26px 0}
video{width:100%;max-height:640px;background:#020617;border-radius:8px}
table{border-collapse:collapse;width:100%;margin-top:16px}td,th{text-align:left;padding:12px 8px;border-bottom:1px solid #2b405d}
th{color:#94a3b8;font-weight:500}td small{display:block;color:#94a3b8;margin-top:6px}
input,select,button,textarea{font:inherit;background:#172840;color:#f1f5f9;border:1px solid #58708c;border-radius:6px;padding:8px}
textarea{width:calc(100% - 20px);min-height:40px}button{cursor:pointer;background:#1d4ed8;font-weight:600}
label{display:inline-block;margin:8px 14px 8px 0}.toolbar{position:sticky;top:0;background:#0b1220f5;padding:14px 0;z-index:1}
.counts{color:#86efac}.source{font-size:13px;color:#fbbf24}@media(max-width:750px){table{display:block;overflow-x:auto}}
</style>
<h1>抽屉示教数据验收</h1>
<p>请结合柜体前视和腕部视角，看完每条轨迹的完整过程。重点检查：是否抓稳把手、机械臂运动是否顺畅、
是否碰到其他部位、抽屉是否正确开合、松手和撤离是否正常，以及最终状态和画面是否清晰。
发现异常碰撞、长时间停顿或视角遮挡，请写入备注。自动检查结果仅供参考，人工验收单独填写。</p>
<p class="source">数据来源：特权状态脚本控制（SCRIPTED_PRIVILEGED_STATE） · 每段视频包含四条独立轨迹 · 尚非 π0.5 模型推理</p>
<div class="toolbar"><label>验收人 <input id="reviewer" placeholder="请输入姓名或昵称"></label>
<button id="export">导出验收记录</button> <span id="counts" class="counts"></span></div>
<div id="packets"></div>
<p>浏览器支持时会自动保存填写进度。完成后请点击“导出验收记录”，保存 JSON 文件；导出内容仍使用原有数据格式，
可直接交给验收校验脚本。验收操作不会修改原始数据集。正式使用验收结果前，请按项目说明运行校验命令。</p>
<script>
const payload=PAYLOAD_JSON;
const cacheKey='cabinet-review-'+payload.inventory_sha256;
let saved={};try{saved=JSON.parse(localStorage.getItem(cacheKey)||'{}')}catch{}
const reviewer=document.getElementById('reviewer');reviewer.value=saved.reviewer||'';
function el(tag,text){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;return e}
const taskLabels={open_top:'打开上层抽屉',open_bottom:'打开下层抽屉',close_top:'关闭上层抽屉',close_bottom:'关闭下层抽屉'};
const splitLabels={train:'训练集',validation:'验证集'};
const decisionLabels={pending:'待验收',accept:'通过',reject:'不通过'};
const reasonLabels={scripted_controller_did_not_complete:'脚本控制过程未完成',scripted_controller_stage_gate_failed:'控制阶段检查未通过',
 task_final_failure:'最终任务状态未达标',not_successful_for_final_10_steps:'最后 10 步未保持成功',non_target_drawer_moved:'非目标抽屉被移动',action_replay_failed:'动作回放未通过'};
const controls=[];
for(const packet of payload.packets){
 const section=el('section');section.append(el('h2',(splitLabels[packet.split]||packet.split)+' · 条件 '+packet.condition_id+' · 随机种子 '+packet.seed));
 const video=el('video');video.controls=true;video.preload='none';video.src=packet.video_url;section.append(video);
 section.append(el('p','视频位置：左上＝打开上层抽屉；右上＝打开下层抽屉；左下＝关闭上层抽屉；右下＝关闭下层抽屉。'));
 const links=el('p');const link=el('a','查看关键帧图');link.href=packet.keyframes_url;link.target='_blank';links.append(link);section.append(links);
 const table=el('table'),head=el('tr');for(const s of ['任务 / 自动检查结果','已看完整段','人工结论','备注 / 不通过原因'])head.append(el('th',s));table.append(head);
 for(const row of packet.episodes){
  const task=taskLabels[row.case]||row.language;
  const tr=el('tr'),info=el('td');info.append(el('strong',task));
  info.append(el('small','原始指令：'+row.language));
  info.append(el('small',row.frames+' 步 · 机器人初始位置：'+(row.robot_side_of_cabinet_world_x==='left'?'左侧':'右侧')+' · 稳定成功：'+(row.stable_success?'是':'否')+' · 回放：'+(row.replay_passed?'通过':'未通过')));
  info.append(el('small','自动筛选：'+(row.selected?'通过':'未通过')+' · 非目标抽屉最大开度变化：'+row.non_target_max_drift.toExponential(2)));
  if(row.rejection_reasons.length)info.append(el('small',row.rejection_reasons.map(r=>reasonLabels[r]||r).join('；')));
  const hash=el('details');hash.append(el('summary','查看原始文件 SHA256'));hash.append(el('code',row.sha256));info.append(hash);tr.append(info);
  const watched=el('input');watched.type='checkbox';watched.setAttribute('aria-label','已看完'+row.id+'（'+task+'）的完整过程');
  const select=el('select');select.setAttribute('aria-label',row.id+'（'+task+'）的人工验收结论');
  for(const s of ['pending','accept','reject']){const o=el('option',decisionLabels[s]);o.value=s;select.append(o)}
  const notes=el('textarea');notes.placeholder='可填写接触、运动或画面问题；不通过时必填';notes.setAttribute('aria-label',row.id+'（'+task+'）的验收备注');
  const old=(saved.episodes||[]).find(r=>r.id===row.id&&r.source_sha256===row.sha256);
  if(old){watched.checked=old.watched_full_episode===true;select.value=old.decision;notes.value=old.reason||''}
  for(const control of [watched,select,notes]){const td=el('td');td.append(control);tr.append(td);control.addEventListener('change',save)}
  table.append(tr);controls.push({row,packet,watched,select,notes});
 }
 section.append(table);document.getElementById('packets').append(section);
}
function decisions(){return {schema:'cabinet_human_review_v1',inventory_sha256:payload.inventory_sha256,
 reviewer:reviewer.value.trim(),created_utc:new Date().toISOString(),
 episodes:controls.map(c=>({id:c.row.id,source_sha256:c.row.sha256,video_sha256:c.packet.video_sha256,
 watched_full_episode:c.watched.checked,decision:c.select.value,reason:c.notes.value.trim()}))}}
function save(){const d=decisions();try{localStorage.setItem(cacheKey,JSON.stringify(d))}catch{}
 const counts={pending:0,accept:0,reject:0};for(const r of d.episodes)counts[r.decision]++;
 document.getElementById('counts').textContent='通过 '+counts.accept+' 条 · 不通过 '+counts.reject+' 条 · 待验收 '+counts.pending+' 条';}
reviewer.addEventListener('change',save);save();
document.getElementById('export').onclick=()=>{const d=decisions();
 if(d.episodes.some(r=>r.decision!=='pending'&&(!d.reviewer||!r.watched_full_episode||(r.decision==='reject'&&!r.reason)))){
 alert('请填写验收人，勾选“已看完整段”，并为每条“不通过”的轨迹填写原因。');return;}
 const url=URL.createObjectURL(new Blob([JSON.stringify(d,null,2)+'\n'],{type:'application/json'}));
 const a=el('a');a.href=url;a.download='review_decisions.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);save();};
</script></html>'''


def build(args):
    if args.output.exists():
        raise FileExistsError("Use a new review directory")
    manifest = read_json(args.manifest)
    if manifest["schema"] not in ("cabinet_sft_selection_v1", "cabinet_sft_union_v1"):
        raise ValueError("Unknown selection schema")
    ids = [r["condition_id"] + "/" + r["case"] for r in manifest["episodes"]]
    if len(ids) != len(set(ids)) or manifest["source"] != "SCRIPTED_PRIVILEGED_STATE":
        raise ValueError("Expected unique, explicitly scripted episode entries")
    packets = {}
    for root in args.review_roots:
        for path in sorted(root.glob("*/report.json")):
            packet = read_json(path)
            if packet.get("schema") != "cabinet_collection_review_v1":
                continue
            video = path.parent / "four_commands.mp4"
            if not packet["decode_all_frames_passed"] or digest(video) != packet["video_sha256"]:
                raise ValueError(f"Review video does not match its report: {video}")
            for source in packet["sources"]:
                if source["sha256"] in packets:
                    raise ValueError("Duplicate review packet for the same recording")
                packets[source["sha256"]] = (path, packet, source)
    groups, rows = {}, []
    for episode in manifest["episodes"]:
        if digest(ROOT / episode["path"]) != episode["sha256"]:
            raise ValueError("Raw episode no longer matches its selection")
        path, packet, source = packets[episode["sha256"]]
        if source["case"] != episode["case"] or source["frames"] != episode["frames"]:
            raise ValueError("Review packet and selection disagree")
        group = groups.setdefault(episode["condition_id"], dict(condition_id=episode["condition_id"],
            split=episode["split"], seed=episode["seed"], report=path.relative_to(ROOT).as_posix(),
            report_sha256=digest(path), video_sha256=packet["video_sha256"], episodes=[]))
        if group["report_sha256"] != digest(path):
            raise ValueError("A condition maps to multiple review packets")
        row = {key:episode[key] for key in ("condition_id", "split", "case", "language", "seed",
            "scene_offset", "frames", "sha256", "path", "source", "robot_side_of_cabinet_world_x",
            "stable_success", "non_target_max_drift", "replay_passed", "selected", "rejection_reasons")}
        row.update(id=episode["condition_id"] + "/" + episode["case"], human_decision="pending")
        group["episodes"].append(row)
        rows.append(row)
    inventory = dict(schema="cabinet_review_inventory_v1", manifest=dict(
        path=args.manifest.relative_to(ROOT).as_posix(), sha256=digest(args.manifest)),
        source="SCRIPTED_PRIVILEGED_STATE", learned_policy=False,
        attempted_episodes=len(rows), automated_selected=sum(r["selected"] for r in rows),
        human_decision_counts=dict(pending=len(rows), accept=0, reject=0),
        packets=list(groups.values()))
    args.output.mkdir(parents=True, exist_ok=False)
    write_new(args.output / "inventory.json", inventory)
    fields = [k for k in rows[0] if k not in ("scene_offset", "rejection_reasons")]
    with (args.output / "episodes.csv").open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    payload = dict(inventory_sha256=digest(args.output / "inventory.json"), packets=inventory["packets"])
    for packet in payload["packets"]:
        directory = (ROOT / packet["report"]).parent
        for key, name in (("video_url", "four_commands.mp4"), ("keyframes_url", "keyframes.png")):
            packet[key] = quote(Path(os.path.relpath(directory / name, args.output)).as_posix(), safe="/")
    page = PAGE.replace("PAYLOAD_JSON", json.dumps(payload, allow_nan=False).replace("<", "\\u003c"))
    (args.output / "index.html").write_text(page, encoding="utf-8", newline="\n")
    print(dict(index=str(args.output / "index.html"), episodes=len(rows), human_accepted=0,
               videos_reused=len(groups)))


def check(args):
    inventory = read_json(args.inventory)
    decisions = read_json(args.decisions)
    if digest(ROOT / inventory["manifest"]["path"]) != inventory["manifest"]["sha256"]:
        raise ValueError("The selection changed after inventory creation")
    if decisions.get("schema") != "cabinet_human_review_v1" or decisions["inventory_sha256"] != digest(args.inventory):
        raise ValueError("Decisions belong to a different inventory")
    known = {row["id"]:(row, packet) for packet in inventory["packets"] for row in packet["episodes"]}
    for packet in inventory["packets"]:
        report = ROOT / packet["report"]
        if digest(report) != packet["report_sha256"] or digest(report.parent / "four_commands.mp4") != packet["video_sha256"]:
            raise ValueError("The reviewed media changed after inventory creation")
    if len(decisions["episodes"]) != len(known) or {r["id"] for r in decisions["episodes"]} != set(known):
        raise ValueError("Missing or repeated review decisions")
    for decision in decisions["episodes"]:
        row, packet = known[decision["id"]]
        if decision["source_sha256"] != row["sha256"] or decision["video_sha256"] != packet["video_sha256"]:
            raise ValueError("Decision references different source bytes")
        if digest(ROOT / row["path"]) != row["sha256"]:
            raise ValueError("Reviewed raw recording changed")
        if decision["decision"] not in ("pending", "accept", "reject"):
            raise ValueError("Unknown decision")
        if decision["decision"] != "pending":
            if not decisions["reviewer"].strip() or decision["watched_full_episode"] is not True:
                raise ValueError("Human name and full-episode viewing declaration required")
            if decision["decision"] == "reject" and not decision["reason"].strip():
                raise ValueError("A rejection requires a reason")
    report = dict(schema="cabinet_human_review_check_v1", created_utc=datetime.now(timezone.utc).isoformat(),
        inventory_sha256=digest(args.inventory), decisions_sha256=digest(args.decisions),
        reviewer=decisions["reviewer"], counts=dict(Counter(r["decision"] for r in decisions["episodes"])),
        evidence="Self-reported human viewing; viewing cannot be verified by this script",
        dataset_modified=False, episodes=decisions["episodes"])
    write_new(args.output, report)
    print(dict(counts=report["counts"], report=str(args.output), dataset_modified=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    index = sub.add_parser("build")
    index.add_argument("--manifest", type=Path, required=True)
    index.add_argument("--review-roots", type=Path, nargs="+", required=True)
    index.add_argument("--output", type=Path, required=True)
    review = sub.add_parser("check")
    review.add_argument("--inventory", type=Path, required=True)
    review.add_argument("--decisions", type=Path, required=True)
    review.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    os.chdir(ROOT)
    for name, value in vars(args).items():
        if isinstance(value, Path):
            setattr(args, name, value.resolve())
    if args.command == "build":
        args.review_roots = [p.resolve() for p in args.review_roots]
        build(args)
    else:
        check(args)


if __name__ == "__main__":
    main()
