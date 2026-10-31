"""ss: the Strands Workshop to Ship kit. Run in your project folder.

  ss init [--example heatsafe] [--update]   set up this folder: a generic starter, or a worked example (never overwrites)
  ss blocks                       the Strands toolbox: 14 runnable blocks and their status
  ss block <name>                 run one block live (tools, mcp, hooks, interventions, graph, swarm, ...)
  ss status                       what is set up, what is measured
  ss bedrock                      one live call to your Bedrock model + Amazon Translate
  ss run "message" [--temp --rh --intensity --sun --job --lat --lon]  run the agent once
  ss cases check | show | approve --by "Name" [--ids a,b]
  ss measure [--limit N]          agent vs single-prompt baseline on the signed cases, gate
  ss video [--spec video.json]    record the demo from a live run (under 3 minutes)
  ss ship                         FACTS.md + SUBMISSION.md (PASS / FAIL / HUMAN)
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent      # .../kit
PROJECT_T = KIT / "project"
EXAMPLES = KIT / "examples"
BLOCKS = KIT / "blocks"
BLOCK_FILES = {"tools": "b01_tools", "mcp": "b02_mcp", "hooks": "b03_hooks", "interventions": "b04_interventions",
               "graph": "b05_graph", "swarm": "b06_swarm", "agents-as-tools": "b07_agents_as_tools", "sessions": "b08_sessions",
               "decider": "b09_decider", "shell": "b10_shell", "harness": "b11_harness", "evals": "b12_evals",
               "voice": "b13_voice", "guardrails": "b14_guardrails"}
BLOCK_STATUS = {"decider": "KEY", "guardrails": "KEY", "voice": "DOC (needs a microphone)"}
GITIGNORE = [".venv/", "__pycache__/", "results/_raw/", "*.webm"]


def _copy(src: Path, dst: Path, done: list, skipped: list, overwrite: bool = False) -> None:
    if src.is_dir():
        for p in sorted(src.rglob("*")):
            if p.is_file() and "__pycache__" not in p.parts:
                _copy(p, dst / p.relative_to(src), done, skipped, overwrite)
        return
    if dst.exists() and not overwrite:
        skipped.append(str(dst))
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    done.append(str(dst))


def cmd_init(a) -> int:
    if not PROJECT_T.is_dir():
        raise SystemExit("init runs from the installed kit: use ~/.strands-ship/bin/ss init (say 'set up strands ship' in Kiro).")
    root, done, skipped = Path.cwd(), [], []
    _copy(KIT / "ship_kit", root / "ship_kit", done, skipped, overwrite=a.update)
    if a.update:
        print(f"Refreshed ship_kit/ ({len(done)} files). Nothing else touched.")
        return 0
    if a.example:
        src = EXAMPLES / a.example
        if not src.is_dir():
            names = sorted(p.name for p in EXAMPLES.iterdir() if p.is_dir())
            raise SystemExit(f"unknown example {a.example!r}; choose one of {', '.join(names)}")
        agent_src, seed, video = src / "agent", src / "cases.seed.jsonl", src / "video.json"
    else:
        agent_src, seed, video = PROJECT_T / "agent", PROJECT_T / "cases.seed.jsonl", PROJECT_T / "video.json"
    _copy(agent_src, root / "agent", done, skipped)
    _copy(seed, root / "cases.jsonl", done, skipped)
    _copy(video, root / "video.json", done, skipped)
    for f in ("requirements.txt", "FAILURES.md"):
        _copy(PROJECT_T / f, root / f, done, skipped)
    for sub in ("steering", "hooks", "agents"):
        _copy(PROJECT_T / sub, root / ".kiro" / sub, done, skipped)
    gi = root / ".gitignore"
    have = gi.read_text().splitlines() if gi.exists() else []
    add = [x for x in GITIGNORE if x not in have]
    if add:
        gi.write_text("\n".join(have + add) + "\n")
    (root / "results").mkdir(exist_ok=True)
    print(("Worked example: " + a.example) if a.example else "Generic starter (your idea goes in IDEA.md, then agent/)")
    print(f"Copied {len(done)} files.")
    if skipped:
        print(f"Kept {len(skipped)} existing files (never overwritten):\n  " + "\n  ".join(skipped))
    print("Next: `ss bedrock`; then say 'brainstorm' in Kiro (or `ss blocks` to see the Strands toolbox).")
    return 0


def cmd_blocks(_a) -> int:
    for name, f in BLOCK_FILES.items():
        doc = (BLOCKS / f"{f}.py").read_text(encoding="utf-8").split('"""')[1].strip().splitlines()[0]
        print(f"{name:16} {BLOCK_STATUS.get(name, 'LIVE'):24} {doc[:90]}")
    print("\nRun one: ss block <name>. Read the code: " + str(BLOCKS) + ". Full map: the ship-design skill's strands-catalogue.md.")
    return 0


def cmd_block(a) -> int:
    f = BLOCK_FILES.get(a.name)
    if not f:
        raise SystemExit(f"unknown block {a.name!r}; one of: {', '.join(BLOCK_FILES)}")
    return subprocess.call([sys.executable, str(BLOCKS / f"{f}.py")], cwd=str(BLOCKS))


def _here() -> None:
    if not (Path.cwd() / "agent").is_dir():
        raise SystemExit("No agent/ here. Run `ss init` in your project folder first.")
    sys.path.insert(0, str(Path.cwd()))


def cmd_status(_a) -> int:
    from . import cases
    print(f"model    {os.environ.get('SHIP_MODEL', 'us.amazon.nova-2-lite-v1:0')}  region {os.environ.get('AWS_REGION', 'us-east-1')}")
    print(f"agent/   {'yes' if Path('agent').is_dir() else 'no (run ss init)'}")
    if Path("cases.jsonl").exists():
        c = cases.check(cases.load())
        print("cases    " + ", ".join(f"{k} {v}" for k, v in c["counts"].items()) + ("" if c["ok"] else "  -> ss cases check"))
    m = Path("results/measure.json")
    if m.exists():
        r = json.loads(m.read_text())
        print(f"measure  {r['when']}: gate {'PASSED' if r['passed'] else 'NOT PASSED'}")
    v = Path("results/video_run.json")
    if v.exists():
        r = json.loads(v.read_text())
        print(f"video    {r['file']} ({r['seconds']} s)")
    return 0


def cmd_bedrock(_a) -> int:
    from strands import Agent
    from strands.models import BedrockModel
    mid, reg = os.environ.get("SHIP_MODEL", "us.amazon.nova-2-lite-v1:0"), os.environ.get("AWS_REGION", "us-east-1")
    try:
        out = Agent(model=BedrockModel(model_id=mid, region_name=reg), callback_handler=None)("Reply with the single word: ready")
        print(f"Bedrock OK  {mid} in {reg}: {str(out).strip()[:40]}")
    except Exception as e:
        msg = str(e)
        print(f"Bedrock FAILED for {mid} in {reg}: {msg[:300]}")
        if "credential" in msg.lower() or "token" in msg.lower():
            print("Fix: run `aws configure` or `aws sso login` in your own terminal; set AWS_PROFILE if not default.")
        elif "access" in msg.lower() or "payment" in msg.lower() or "marketplace" in msg.lower():
            print("Fix: enable the model in the Bedrock console (Model access) or pick another one with SHIP_MODEL.")
        return 1
    try:
        import boto3
        t = boto3.client("translate", region_name=reg).translate_text(Text="Drink water.", SourceLanguageCode="en", TargetLanguageCode="ta")
        print(f"Translate OK  en->ta: {t['TranslatedText']}")
    except Exception as e:
        print(f"Translate FAILED (Tamil fallback will not work): {str(e)[:200]}")
        return 1
    return 0


def cmd_run(a, rest) -> int:
    _here()
    return subprocess.call([sys.executable, "-m", "agent.app", *rest])


def cmd_cases(a) -> int:
    from . import cases
    cs = cases.load()
    if a.action == "approve":
        n = cases.approve(cs, a.by, a.ids.split(",") if a.ids else None)
        cases.save(cs)
        print(f"Signed off {n} cases as {a.by}.")
    if a.action == "show":
        for c in cs:
            e = c["expected"]
            print(f"{c['id']:12} {c.get('lang','en')} {c['job'][:14]:14} {c['temp_c']}C/{c['rh']}% {c.get('intensity','')[:5]:5} "
                  f"-> {e['risk_level']:8} {e['escalation']:9} {'signed ' + c['signed_off_by'] if c.get('signed_off_by') else 'UNSIGNED'}")
            print(f"{'':12} {c['text']}")
        return 0
    r = cases.check(cs)
    print("counts: " + ", ".join(f"{k} {v}" for k, v in r["counts"].items()))
    for e in r["errors"]:
        print("ERROR " + e)
    for s in r["below_minimum"]:
        print("BELOW MINIMUM " + s)
    if r["unsigned"]:
        print(f"UNSIGNED {len(r['unsigned'])}: read each label (`ss cases show`), then `ss cases approve --by \"Your Name\"`")
    print("OK" if r["ok"] else "NOT READY")
    return 0 if r["ok"] or a.action == "approve" else 1


def cmd_measure(a) -> int:
    _here()
    from . import measure
    return measure.main(a.limit, a.workers)


def cmd_video(a) -> int:
    _here()
    from . import video
    r = video.record(a.spec)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    return 0 if r["under_3_min"] and all(s["exit"] == 0 for s in r["scenes"]) else 1


def cmd_ship(_a) -> int:
    from . import submit
    return submit.main()


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(prog="ss", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("init")
    p.add_argument("--example", help="copy a worked example instead of the generic starter (heatsafe)")
    p.add_argument("--update", action="store_true", help="refresh ship_kit/ only")
    sp.add_parser("blocks")
    p = sp.add_parser("block")
    p.add_argument("name")
    sp.add_parser("status")
    sp.add_parser("bedrock")
    sp.add_parser("run", add_help=False)
    p = sp.add_parser("cases")
    p.add_argument("action", choices=["check", "show", "approve"], nargs="?", default="check")
    p.add_argument("--by")
    p.add_argument("--ids")
    p = sp.add_parser("measure")
    p.add_argument("--limit", type=int)
    p.add_argument("--workers", type=int, default=3)
    p = sp.add_parser("video")
    p.add_argument("--spec", default="video.json")
    sp.add_parser("ship")
    if argv[:1] == ["run"]:
        return cmd_run(None, argv[1:])
    a = ap.parse_args(argv)
    return {"init": cmd_init, "blocks": cmd_blocks, "block": cmd_block, "status": cmd_status, "bedrock": cmd_bedrock, "cases": cmd_cases,
            "measure": cmd_measure, "video": cmd_video, "ship": cmd_ship}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
