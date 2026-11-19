"""Run the four drawer commands on one existing validation initialization.

PI05 needs an actual model endpoint. --replay-condition instead checks recorded
action transport using the existing runner; it never establishes model ability.
--dry-run only prints the request and commands, without starting simulation.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
CASES = (
    ('open_top', 'OpenDrawerPairLite', 'Open the top drawer.'),
    ('open_bottom', 'OpenDrawerPairLite', 'Open the bottom drawer.'),
    ('close_top', 'CloseDrawerPairLite', 'Close the top drawer.'),
    ('close_bottom', 'CloseDrawerPairLite', 'Close the bottom drawer.'),
)


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def write_new(path, value):
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write('\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--endpoint', help='Actual PI05 /predict URL, typically through an existing local tunnel')
    mode.add_argument('--replay-condition', type=Path, help='Existing four-command raw recordings; diagnostic replay only')
    parser.add_argument('--checkpoint-id', help='Exact checkpoint identity published by the actual model service')
    parser.add_argument('--plan', type=Path, default=ROOT / 'configs/data_splits_v4.json')
    parser.add_argument('--condition-id', default='validation_001')
    parser.add_argument('--release', type=Path, default=ROOT / 'configs/sft_release_v1.json')
    parser.add_argument('--horizon', type=int, default=50)
    parser.add_argument('--execute-steps', type=int, default=5)
    parser.add_argument('--timeout', type=float, default=30.)
    parser.add_argument('--no-video', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.execute_steps <= args.horizon <= 128 or not 0 < args.timeout <= 300:
        parser.error('Expected 1 <= execute_steps <= horizon <= 128 and timeout in (0,300]')
    for key in ('plan', 'release', 'output', 'replay_condition'):
        value = getattr(args, key)
        if value is not None:
            setattr(args, key, value.resolve())
    if args.output.exists():
        parser.error('Output must be new; existing results are never overwritten')
    if args.endpoint:
        url = urlsplit(args.endpoint)
        if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password or url.query or url.fragment:
            parser.error('Use a plain HTTP(S) endpoint without credentials, query or fragment')
        if not args.checkpoint_id or not args.checkpoint_id.strip() or len(args.checkpoint_id) > 256:
            parser.error('PI05 requires the actual server checkpoint ID (1..256 characters)')
    elif args.checkpoint_id or (args.horizon, args.execute_steps) != (50, 5):
        parser.error('Replay uses source checkpoint hashes and the existing H=50/k=5 diagnostic')

    release, plan = read(args.release), read(args.plan)
    if release.get('schema') != 'cabinet_sft_release_v1' or plan.get('schema') != 'cabinet_split_plan_v1':
        raise ValueError('Unknown release or collection plan schema')
    if digest(args.plan) not in {entry['sha256'] for entry in release['collection_plans']}:
        raise ValueError('Smoke initialization plan is not bound to this release')
    conditions = [row for row in plan['conditions'] if row['id'] == args.condition_id]
    if len(conditions) != 1 or conditions[0]['split'] != 'validation':
        raise ValueError('Smoke runs use an existing validation initialization, never reserved tests or training')
    condition = conditions[0]
    if plan['front_camera'] != 'cabinet_front' or plan['pair_layout'] != 'spaced':
        raise ValueError('Expected the v1 cabinet-front / spaced drawer contract')
    if {entry['language'] for entry in release['splits']['validation']['episode_order']} != {row[2] for row in CASES}:
        raise ValueError('Release validation does not contain all four drawer commands')
    if {entry['id'].split('/')[0] for entry in release['splits']['validation']['episode_order']} != {args.condition_id}:
        raise ValueError('Condition differs from the frozen validation membership')
    for name, expected in release['immutable_code_sha256'].items():
        if digest(ROOT / name) != expected:
            raise ValueError(f'Frozen simulation/data code changed: {name}')

    if args.replay_condition:
        expected = {row['id'].split('/')[1]: row['source_sha256'] for row in release['splits']['validation']['episode_order']}
        for case, _, _ in CASES:
            if digest(args.replay_condition / case / 'episode.hdf5') != expected[case]:
                raise ValueError(f'Replay source differs from frozen validation: {case}')

    commands = []
    for case, task, instruction in CASES:
        command = [sys.executable, str(ROOT / 'scripts/remote_policy_rollout.py'),
            '--expected-mode', 'PI05', '--endpoint', args.endpoint or '<unused-in-replay>',
            '--checkpoint-id', args.checkpoint_id or '<source-recording-hash>',
            '--task', task, '--instruction', instruction, '--seed', str(condition['seed']),
            '--scene-offset', *map(str, condition['scene_offset']), '--pair-layout', plan['pair_layout'],
            '--front-camera', plan['front_camera'], '--horizon', str(args.horizon),
            '--execute-steps', str(args.execute_steps), '--timeout', str(args.timeout),
            '--max-steps', '600', '--output', str(args.output / case)]
        if args.no_video:
            command.append('--no-video')
        commands.append(dict(case=case, command=command if args.endpoint else None,
            replay_source=str(args.replay_condition / case / 'episode.hdf5') if args.replay_condition else None))
    request = dict(schema='cabinet_four_command_smoke_request_v1',
        created_utc=datetime.now(timezone.utc).isoformat(),
        mode='PI05' if args.endpoint else 'RECORDED_ACTION_CHUNKS',
        release=dict(id=release['release_id'], sha256=digest(args.release)),
        initialization=dict(plan_sha256=digest(args.plan), **condition),
        checkpoint_id=args.checkpoint_id, horizon=args.horizon, execute_steps=args.execute_steps,
        control_hz=20, max_control_steps=600, commands=commands,
        reserved_tests_executed=False, purpose='Four-command smoke on one known validation initialization; not a success-rate benchmark',
        checkpoint_loading_evidence='Actual PI05 weight/processor loading must be documented by the server; this client cannot attest it')
    if args.dry_run:
        print(json.dumps(dict(dry_run=True, simulation_started=False, request=request), indent=2))
        return

    args.output.mkdir(parents=True, exist_ok=False)
    write_new(args.output / 'request.json', request)
    summary = dict(schema='cabinet_four_command_smoke_v1', mode=request['mode'],
        learned_policy=args.endpoint is not None, initialization=request['initialization'],
        release=request['release'], checkpoint_id=args.checkpoint_id,
        purpose=request['purpose'], reserved_tests_executed=False,
        runner_sha256=digest(Path(__file__)), rows=[], infrastructure_passed=False,
        all_four_stable_successes=False, error=None)
    failed = False
    try:
        for item in commands:
            if args.replay_condition:
                from check_remote_chunks import run_check
                checked = run_check(Path(item['replay_source']), args.output / item['case'], video=not args.no_video)
                report = checked['report']
                report_path = args.output / item['case'] / 'rollout/report.json'
            else:
                with (args.output / (item['case'] + '.log')).open('x', encoding='utf-8') as log:
                    process = subprocess.run(item['command'], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                report_path = args.output / item['case'] / 'report.json'
                if not report_path.exists():
                    raise RuntimeError(f'No rollout report; inspect {item["case"]}.log')
                report = read(report_path)
                if process.returncode != 0:
                    raise RuntimeError(f'Client failed: {item["case"]}; inspect its log and report')
            expected_task = next(task for case, task, _ in CASES if case == item['case'])
            expected_instruction = next(text for case, _, text in CASES if case == item['case'])
            if (report['mode'] != summary['mode'] or report['learned_policy'] is not summary['learned_policy']
                or report['task'] != expected_task or report['language'] != expected_instruction
                or report['seed'] != condition['seed'] or report['horizon'] != args.horizon
                or report['execute_steps'] != args.execute_steps or report['max_control_steps'] != 600
                or report['scene_parameters'] != dict(instruction=expected_instruction,
                    scene_offset=condition['scene_offset'], pair_layout=plan['pair_layout'], front_camera=plan['front_camera'])
                or report['simulation_advances_while_waiting'] or report['rejected_requests']
                or (args.endpoint and report['checkpoint_id'] != args.checkpoint_id)):
                raise RuntimeError('Rollout provenance, scene or transport checks failed')
            summary['rows'].append(dict(case=item['case'], instruction=expected_instruction,
                report=report_path.relative_to(args.output).as_posix(), report_sha256=digest(report_path),
                checkpoint_id=report['checkpoint_id'], steps=report['steps'], stop_reason=report['stop_reason'],
                success_final=report['success_final'], success_stable_last_10=report['success_stable_last_10'],
                evaluation=report.get('evaluation'), requests=report['accepted_requests'],
                latency_seconds=report['latency_seconds']))
            print(json.dumps(dict(case=item['case'], mode=summary['mode'],
                stable_success=report['success_stable_last_10'], steps=report['steps'])), flush=True)
        summary['infrastructure_passed'] = len(summary['rows']) == 4
        summary['all_four_stable_successes'] = len(summary['rows']) == 4 and all(row['success_stable_last_10'] for row in summary['rows'])
    except Exception as error:
        failed = True
        summary['error'] = dict(type=type(error).__name__, message=str(error))
    finally:
        summary['completed_utc'] = datetime.now(timezone.utc).isoformat()
        write_new(args.output / 'report.json', summary)
        lines = ['# Four-command smoke', '', f'Mode: `{summary["mode"]}`. {summary["purpose"]}', '',
            '| Command | Final success | Stable last 10 | Steps | Report |', '|---|---|---|---:|---|']
        for row in summary['rows']:
            lines.append(f'| {row["instruction"]} | {row["success_final"]} | {row["success_stable_last_10"]} | {row["steps"]} | [JSON]({row["report"]}) |')
        lines.extend(['', 'Task failures remain results; infrastructure errors stop the run.',
            'A requested PI05 mode is not independent evidence that the server loaded model weights.',
            'Recorded replay is a transport diagnostic and cannot establish model performance.',
            '', f'Infrastructure passed: {summary["infrastructure_passed"]}.'])
        if summary['error']:
            lines.append(f'Error: {summary["error"]["message"]}')
        with (args.output / 'report.md').open('x', encoding='utf-8', newline='\n') as stream:
            stream.write('\n'.join(lines) + '\n')
    if failed:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
