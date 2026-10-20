"""Create/revoke READ_ONLY accounts; never accept a password on the command line."""
import argparse
import getpass
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.demo_access import make_user


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['add','revoke','list'])
    parser.add_argument('email',nargs='?')
    parser.add_argument('--replace',action='store_true')
    args=parser.parse_args()
    target=Path(__file__).resolve().parents[1]/'private/demo_users.json'
    users=json.loads(target.read_text(encoding='utf-8')) if target.exists() else {'users':{}}
    if args.action=='list':
        for email in sorted(users['users']):print(email,'READ_ONLY')
        return
    email=(args.email or '').strip().casefold()
    if '@' not in email or ':' in email or len(email)>254:parser.error('Specify the employee email')
    if args.action=='add':
        if email in users['users'] and not args.replace:parser.error('Account exists; use --replace for password rotation')
        password=getpass.getpass('Password (16+ characters): ')
        if password!=getpass.getpass('Repeat password: '):parser.error('Passwords do not match')
        users['users'][email]=make_user(password)
    else:
        if email not in users['users']:parser.error('Account not found')
        del users['users'][email]
    target.parent.mkdir(parents=True,exist_ok=True)
    if os.name=='nt':
        account=os.environ.get('USERDOMAIN','')+'\\'+getpass.getuser()
        subprocess.run(['icacls',str(target.parent),'/inheritance:r','/grant:r',account+':(OI)(CI)F'],check=True,capture_output=True)
    with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=target.parent,delete=False) as stream:
        json.dump(users,stream,ensure_ascii=False,indent=2);temporary=Path(stream.name)
    os.chmod(temporary,0o600);temporary.replace(target)
    print('READ_ONLY account '+args.action+': '+email)


if __name__=='__main__':main()
