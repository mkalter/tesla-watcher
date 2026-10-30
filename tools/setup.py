"""Create private local web settings; ntfy topic is generated on first start."""
from pathlib import Path
import secrets
root=Path(__file__).resolve().parents[1]
path=root/'.env'
if path.exists():
    print('.env bestaat al; bestaande instellingen blijven behouden.')
else:
    path.write_text('ADMIN_PASSWORD='+secrets.token_urlsafe(36)+'\nNTFY_SERVER=https://ntfy.sh\n',encoding='utf-8')
    path.chmod(0o600)
    print('Private .env gemaakt. Login als admin met het wachtwoord uit .env. De ntfy-topic staat na starten in het webscherm.')
