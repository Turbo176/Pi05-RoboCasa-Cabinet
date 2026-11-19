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
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Cabinet demonstration review</title>
<style>
:root{color-scheme:dark;font:16px system-ui;background:#0b1220;color:#e2e8f0}
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
<h1>Drawer demonstration review</h1>
<p>Watch each complete episode in both recorded policy views. Check handle contact, arm motion,
drawer motion, release, visibility and the final state. Mark unwanted contact, long stalls or
poor camera coverage in the notes. Automated success and replay checks remain separate.</p>
<p class="source">SCRIPTED_PRIVILEGED_STATE · Four independent episodes per video · No π0.5 inference</p>
<div class="toolbar"><label>Reviewer <input id="reviewer" placeholder="Your name"></label>
<button id="export">Export decisions</button> <span id="counts" class="counts"></span></div>
<div id="packets"></div>
<p>Decisions are saved in this browser and exported as a local JSON file. The dataset and original
selection files are unchanged. Run the check command in the guide before using any annotations.</p>
<script>
const payload=PAYLOAD_JSON;
const cacheKey='cabinet-review-'+payload.inventory_sha256;
let saved={};try{saved=JSON.parse(localStorage.getItem(cacheKey)||'{}')}catch{}
const reviewer=document.getElementById('reviewer');reviewer.value=saved.reviewer||'';
function el(tag,text){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;return e}
const controls=[];
for(const packet of payload.packets){
 const section=el('section');section.append(el('h2',packet.condition_id+' · seed '+packet.seed+' · '+packet.split));
 const video=el('video');video.controls=true;video.preload='none';video.src=packet.video_url;section.append(video);
 const links=el('p');const link=el('a','Open keyframe sheet');link.href=packet.keyframes_url;link.target='_blank';links.append(link);section.append(links);
 const table=el('table'),head=el('tr');for(const s of ['Episode / automated checks','Watched in full','Human decision','Notes'])head.append(el('th',s));table.append(head);
 for(const row of packet.episodes){
  const tr=el('tr'),info=el('td');info.append(el('strong',row.language));
  info.append(el('small',row.frames+' actions · robot '+row.robot_side_of_cabinet_world_x+' · stable '+row.stable_success+' · replay '+row.replay_passed));
  info.append(el('small','Automatic selection: '+(row.selected?'eligible':'rejected')+' · non-target drift '+row.non_target_max_drift.toExponential(2)));
  if(row.rejection_reasons.length)info.append(el('small',row.rejection_reasons.join('; ')));
  const hash=el('details');hash.append(el('summary','Source SHA256'));hash.append(el('code',row.sha256));info.append(hash);tr.append(info);
  const watched=el('input');watched.type='checkbox';watched.setAttribute('aria-label','Watched '+row.id+' in full');
  const select=el('select');select.setAttribute('aria-label','Decision for '+row.id);
  for(const s of ['pending','accept','reject']){const o=el('option',s);o.value=s;select.append(o)}
  const notes=el('textarea');notes.setAttribute('aria-label','Notes for '+row.id);
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
 document.getElementById('counts').textContent=counts.accept+' accepted · '+counts.reject+' rejected · '+counts.pending+' pending';}
reviewer.addEventListener('change',save);save();
document.getElementById('export').onclick=()=>{const d=decisions();
 if(d.episodes.some(r=>r.decision!=='pending'&&(!d.reviewer||!r.watched_full_episode||(r.decision==='reject'&&!r.reason)))){
 alert('Enter a reviewer name, confirm the complete episode was watched, and give a reason for every rejection.');return;}
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
