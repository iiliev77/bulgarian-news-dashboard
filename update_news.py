import json,re
from datetime import datetime,timezone
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

H={"User-Agent":"Mozilla/5.0 (compatible; BG-News-Dashboard/1.0)"}

def clean(s): return re.sub(r"\s+"," ",s or "").strip()

def get(url):
    r=requests.get(url,headers=H,timeout=25)
    r.raise_for_status()
    return r.text

def darik(html):
    s=BeautifulSoup(html,"html.parser"); out=[]; seen=set()
    for a in s.find_all("a",href=True):
        u=urljoin("https://dariknews.bg",a["href"]); t=clean(a.get_text(" ",strip=True))
        if len(t)<12 or not re.match(r"^https://dariknews\.bg/novini/[^?#]+",u): continue
        if t.lower() in {"новини","последни новини","виж всички","още"} or u in seen: continue
        seen.add(u); out.append({"title":t,"url":u})
        if len(out)>=10: break
    return out

def gong(html):
    s=BeautifulSoup(html,"html.parser"); out=[]; seen=set()
    blocked=("/search","/author","/tag","/video","/multimedia","/login","/register","/profile","/gallery")
    for a in s.find_all("a",href=True):
        u=urljoin("https://gong.bg",a["href"]); t=clean(a.get_text(" ",strip=True))
        p=u.replace("https://gong.bg","")
        if len(t)<15 or not re.match(r"^https://gong\.bg/[^?#]+",u) or p.count("/")<2: continue
        if any(x in p for x in blocked) or u in seen: continue
        seen.add(u); out.append({"title":t,"url":u})
        if len(out)>=10: break
    return out

try: news=darik(get("https://dariknews.bg/novini"))
except Exception as e: print("Darik error:",repr(e)); news=[]
try: sport=gong(get("https://gong.bg"))
except Exception as e: print("Gong error:",repr(e)); sport=[]

try:
    old=json.load(open("news.json",encoding="utf-8"))
except Exception: old={}
if not news: news=old.get("news",[])
if not sport: sport=old.get("sport",[])

data={"updated":datetime.now(timezone.utc).isoformat(),"news":news,"sport":sport}
with open("news.json","w",encoding="utf-8") as f: json.dump(data,f,ensure_ascii=False,indent=2)
print("Darik:",len(news),"Gong:",len(sport))
