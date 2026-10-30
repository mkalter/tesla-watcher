"""Generate local secrets and a Docker config. Does not send or deploy anything."""
from pathlib import Path
import json,secrets,re
root=Path(__file__).resolve().parents[1]
path=root/'.env'
if path.exists():
 print('.env already exists; keeping existing settings.')
else:
 number=input('Your receiving WhatsApp number, with country code (e.g. 31612345678): ').strip().lstrip('+').replace(' ','')
 if not re.fullmatch(r'\d{8,15}',number):raise SystemExit('Invalid number: use digits and country code only.')
 path.write_text('BRIDGE_TOKEN='+secrets.token_urlsafe(36)+'\nWHATSAPP_TO='+number+'\n')
 path.chmod(0o600)
 print('Created .env. It contains your private pairing password; do not share it.')
config=root/'config.docker.json'
if not config.exists():
 c=json.loads((root/'config.json').read_text());c['notifications']={'enabled':False,'bridge_url':'http://whatsapp:3000'}
 config.write_text(json.dumps(c,indent=2))
 print('Created config.docker.json. WhatsApp sending stays disabled until you finish pairing and testing.')
