#!/usr/bin/env python3
"""Rotate the Goal HQ dashboard password (public/landings/hq/).

Usage: python scripts/goalhq_set_password.py OLD_PASSWORD NEW_PASSWORD

Re-encrypts the state under the new password's key and writes it to a new
row id derived from the new password. The old row is overwritten with a
tombstone so the old password stops working. Requires .env (SUPABASE_URL,
SUPABASE_ANON_KEY) and pip packages: cryptography.
"""
import os, sys, json, hashlib, base64, urllib.request
from pathlib import Path
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

SALT = "aghq-v1-7c1f"
ROOT = Path(__file__).resolve().parent.parent
for line in open(ROOT/".env"):
    line=line.strip()
    if line and not line.startswith("#") and "=" in line:
        k,v=line.split("=",1); os.environ.setdefault(k.strip(),v.strip())
URL=os.environ["SUPABASE_URL"]+"/rest/v1/goal_dashboard"; KEY=os.environ["SUPABASE_ANON_KEY"]
HDR={"apikey":KEY,"Authorization":"Bearer "+KEY,"Content-Type":"application/json","Prefer":"resolution=merge-duplicates"}

def kdf(pw):
    rid=hashlib.sha256(("row:"+pw+":"+SALT).encode()).hexdigest()
    k=hashlib.pbkdf2_hmac("sha256",pw.encode(),SALT.encode(),310000,dklen=32)
    return rid,k

def main():
    old_pw,new_pw=sys.argv[1],sys.argv[2]
    oid,ok=kdf(old_pw); nid,nk=kdf(new_pw)
    r=urllib.request.urlopen(urllib.request.Request(URL+"?id=eq."+oid+"&select=payload",headers=HDR))
    rows=json.loads(r.read())
    if not rows: sys.exit("Old password not found (wrong password?)")
    iv,ct=[base64.b64decode(x) for x in rows[0]["payload"].split(".")]
    state=AESGCM(ok).decrypt(iv,ct,None)
    niv=os.urandom(12)
    payload=base64.b64encode(niv).decode()+"."+base64.b64encode(AESGCM(nk).encrypt(niv,state,None)).decode()
    body=json.dumps([{"id":nid,"payload":payload},{"id":oid,"payload":"retired"}]).encode()
    urllib.request.urlopen(urllib.request.Request(URL+"?on_conflict=id",data=body,headers=HDR,method="POST"))
    print("Password rotated. New row:",nid[:12]+"...  Old row tombstoned.")

if __name__=="__main__": main()
