"""Cross-platform launcher: load local .env without executing shell code."""
import os,subprocess,sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]
env=os.environ.copy()
env.setdefault('PYTHONUTF8','1')
if (root/'.env').exists():
 for line in (root/'.env').read_text().splitlines():
  if line.strip() and not line.lstrip().startswith('#') and '=' in line:
   key,value=line.split('=',1)
   if key in ('BRIDGE_TOKEN','WHATSAPP_TO','CHROMIUM_PATH','CHROME_NO_SANDBOX','BRIDGE_DATA','HOST','PORT'):
    env[key]=value.strip()
if len(sys.argv)<2:raise SystemExit('Usage: python tools/run.py bridge | scan | run | status | events | ...')
args=['node','bridge/server.js'] if sys.argv[1]=='bridge' else [sys.executable,'-m','watcher.cli',*sys.argv[1:]]
try:raise SystemExit(subprocess.call(args,cwd=root,env=env))
except KeyboardInterrupt:raise SystemExit(130)
