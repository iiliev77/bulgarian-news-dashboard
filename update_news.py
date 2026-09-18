import json,re
from datetime import datetime,timezone
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

HEADERS={"User-Agent":"Mozilla/5.0 (compatible; BulgarianNewsDashboard/1.0)"}
SOURCES={"darik":"https://dariknews.bg/novini","dsport":"https://dsport.bg/"}

def clean(s): return re.sub(r"\s+"," ",s or "").strip()

def fetch(url,source):
    r=requests.get(url,headers=HEADERS,timeout=25)
    r.raise_for_status()
    soup=BeautifulSoup(r.text,"html.parser")
    out=[]; seen=set()
    for a in soup.find_all("a",href=True):
        title=clean(a.get_text(" ",strip=True)); href=urljoin(url,a["href"])
        if not title or len(title)<18 or len(title)>220 or href in seen: continue
        if source=="darik":
            if "dariknews.bg" not in href or not re.search(r"\.html(?:[?#].*)?$",href): continue
        else:
            if "dsport.bg" not in href or not re.search(r"\.html(?:[?#].*)?$",href): continue
        if title.lower() in {"виж всички","прочети повече","вход","регистрация"}: continue
        seen.add(href)
        context=clean(a.parent.get_text(" ",strip=True)) if a.parent else ""
        m=re.search(r"\b\d{1,2}\s+(?:Яну|Фев|Мар|Апр|Май|Юни|Юли|Авг|Сеп|Окт|Ное|Дек)(?:\s*\|\s*\d{1,2}:\d{2})?|\b\d{1,2}:\d{2}\b",context,re.I)
        item={"title":title,"url":href}
        if m:item["time"]=m.group(0)
        out.append(item)
        if len(out)>=15: break
    return out

data={"updated_at":datetime.now(timezone.utc).isoformat(),"darik":[],"dsport":[]}
for key,url in SOURCES.items():
    try:data[key]=fetch(url,key)
    except Exception as e: print(key,e)
with open("news.json","w",encoding="utf-8") as f: json.dump(data,f,ensure_ascii=False,indent=2)
print("Darik:",len(data["darik"]),"Dsport:",len(data["dsport"]))
