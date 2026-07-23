import streamlit as st
import requests
import json
import os
import math
import pandas as pd
import urllib3

# --- КОНФИГУРАЦИЯ ---
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Налог с продаж в игре (Accounting skill)
# 5.0% - база, 4.2% - при прокачке в 5. 
# Вы упомянули 4.6%, будем использовать этот коэффициент.
SALES_TAX_PERCENT = 4.6 
TAX_COEFF = (100 - SALES_TAX_PERCENT) / 100 # 0.954

RESOURCE_GROUPS = {
    "Минералы": ["Tritanium", "Pyerite", "Mexallon", "Isogen", "Nocxium", "Zydrine", "Megacyte", "Morphite"],
    "Планетарка": ["Coolant", "Construction Blocks", "Consumer Electronics", "Enriched Uranium", "Robotics", "Nanites", "Mechanical Parts"],
    "Топливо": ["Nitrogen Isotopes", "Hydrogen Isotopes", "Helium Isotopes", "Oxygen Isotopes", "Liquid Ozone", "Heavy Water", "Strontium Clathrates"],
    "Газы и Руды": ["Atmospheric Gases", "Evaporate Deposits", "Hydrocarbons", "Silicates", "Fullerite"],
    "Сальваг": ["Nanite Repair Paste", "R.A.M.- Robotics", "R.A.M.- Ship Tech"]
}
BASE_RESOURCES_SET = {item.lower() for sublist in RESOURCE_GROUPS.values() for item in sublist}

HIGHSEC_REGIONS = {
    10000002: "The Forge", 10000043: "Domain", 10000032: "Sinq Laison",
    10000042: "Metropolis", 10000030: "Heimatar", 10000033: "Essence",
    10000067: "Genesis", 10000037: "Everyshore", 10000068: "Verge Vendor"
}

HUBS = {
    "Jita": {"system_id": 30000142, "region_id": 10000002, "station_id": 60003760},
    "Amarr": {"system_id": 30002187, "region_id": 10000043, "station_id": 60008494},
    "Dodixie": {"system_id": 30002659, "region_id": 10000032, "station_id": 60011866},
    "Rens": {"system_id": 30002510, "region_id": 10000030, "station_id": 60004588},
    "Hek": {"system_id": 30002053, "region_id": 10000042, "station_id": 60005686}
}

# --- КЭШ ---
def load_json(path):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f: return json.load(f)
        except: return {}
    return {}

def save_json(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=4)
    except: pass

if 'id_map' not in st.session_state: st.session_state.id_map = load_json("id_map.json")
if 'cache_name' not in st.session_state: st.session_state.cache_name = load_json("names_db.json")

# --- API ---
def get_names_batch(ids):
    ids_to_fetch = list(set([int(tid) for tid in ids if str(tid) not in st.session_state.cache_name]))
    if ids_to_fetch:
        try:
            for i in range(0, len(ids_to_fetch), 1000):
                chunk = ids_to_fetch[i:i+1000]
                r = requests.post("https://esi.evetech.net/latest/universe/names/", json=chunk, timeout=20).json()
                for item in r: st.session_state.cache_name[str(item['id'])] = item['name']
            save_json("names_db.json", st.session_state.cache_name)
        except: pass
    return st.session_state.cache_name

def fetch_recipe(tid):
    try:
        h = {'User-Agent': 'Mozilla/5.0'}
        r = requests.get(f"https://www.fuzzwork.co.uk/blueprint/api/blueprint.php?typeid={tid}", timeout=10, verify=False, headers=h).json()
        if 'activityMaterials' in r:
            am = r['activityMaterials']
            k = next((x for x in ['1','11'] if str(x) in am or x in am), next(iter(am.keys())) if am else None)
            if k:
                mats = am[str(k)] if str(k) in am else am[k]
                yld = 1
                if 'activityProducts' in r:
                    ap = r['activityProducts']
                    act_key = str(k) if str(k) in ap else (k if k in ap else None)
                    if act_key: yld = int(ap[act_key][0]['quantity'])
                return mats, yld
    except: pass
    return None, 0

# --- ИНТЕРФЕЙС ---
st.set_page_config(page_title="EVE Master v12.5", layout="wide")
st.title("🛰️ EVE Online Master: Trade & Industry")

t1, t2, t3, t4 = st.tabs(["Арбитраж", "Срез цен", "Чертежи", "Глобальный поиск"])

with t1:
    col1, col2, col3 = st.columns(3)
    with col1: f_hub = st.selectbox("Из системы (Sell)", list(HUBS.keys()), index=0, key="m1f")
    with col2: t_hub = st.selectbox("В хаб (Buy)", list(HUBS.keys()), index=1, key="m1t")
    with col3: m1_pct = st.number_input("Мин. %", 1, 1000, 40, key="m1p")
    
    if st.button("Запустить Арбитраж"):
        h1, h2 = HUBS[f_hub], HUBS[t_hub]
        with st.spinner("Анализ рынков..."):
            # Sell
            s_data = {}
            for p in range(1, 15):
                d = requests.get(f"https://esi.evetech.net/latest/markets/{h1['region_id']}/orders/", params={'order_type': 'sell', 'page': p}).json()
                if not d or 'error' in d: break
                for o in d:
                    if o['location_id'] == h1['station_id']:
                        tid = o['type_id']
                        if tid not in s_data or o['price'] < s_data[tid]['p']: s_data[tid] = {'p': o['price'], 'q': o['volume_remain']}
                if len(d) < 1000: break
            # Buy
            b_data = {}
            for p in range(1, 15):
                d = requests.get(f"https://esi.evetech.net/latest/markets/{h2['region_id']}/orders/", params={'order_type': 'buy', 'page': p}).json()
                if not d or 'error' in d: break
                for o in d:
                    if o['location_id'] == h2['station_id']:
                        tid = o['type_id']
                        if tid in s_data:
                            if tid not in b_data or o['price'] > b_data[tid]['p']: b_data[tid] = {'p': o['price'], 'q': o['volume_remain']}
                if len(d) < 1000: break
            
            res = []
            for tid, b in b_data.items():
                s = s_data[tid]
                diff = ((b['p'] - s['p'])/s['p'])*100
                if diff >= m1_pct:
                    # РАСЧЕТ: (Чистая выручка после налога) - Затраты
                    prof = (b['p'] * TAX_COEFF - s['p']) * min(s['q'], b['q'])
                    if prof > 0: res.append([tid, s['p'], s['q'], b['p'], b['q'], diff, prof])
            
            if res:
                get_names_batch([x[0] for x in res])
                df = pd.DataFrame(res, columns=["id", "Цена Sell", "Кол S", "Цена Buy", "Кол B", "Профит %", "Прибыль ISK"])
                df["Товар"] = df["id"].apply(lambda x: st.session_state.cache_name.get(str(x), str(x)))
                st.dataframe(df[["Товар", "Цена Sell", "Кол S", "Цена Buy", "Кол B", "Профит %", "Прибыль ISK"]].sort_values("Профит %", ascending=False), use_container_width=True)

with t4:
    m4_min_pct = st.slider("Мин. % профита", 10, 100, 40, key="m4_sl")
    if st.button("Начать Глобальный скан High-Sec"):
        bar = st.progress(0); st_txt = st.empty()
        hb = {}
        # Хабы
        for i, (hn, info) in enumerate(HUBS.items()):
            st_txt.text(f"Хаб {hn}: сбор спроса...")
            d = requests.get(f"https://esi.evetech.net/latest/markets/{info['region_id']}/orders/", params={'order_type': 'buy'}).json()
            for o in d:
                if o['system_id'] == info['system_id']:
                    t = o['type_id']
                    if t not in hb or o['price'] > hb[t]['p']: hb[t] = {'p': o['price'], 'h': hn, 'q': o['volume_remain']}
            bar.progress((i+1)*5 // 14)
        
        res_l = []
        # Регионы
        for i, (rid, rname) in enumerate(HIGHSEC_REGIONS.items()):
            st_txt.text(f"Регион {rname}: поиск предложений...")
            for p in range(1, 12):
                d = requests.get(f"https://esi.evetech.net/latest/markets/{rid}/orders/", params={'order_type': 'sell', 'page': p}).json()
                if not d or 'error' in d: break
                for o in d:
                    t = o['type_id']
                    if t in hb:
                        diff = ((hb[t]['p'] - o['price'])/o['price'])*100
                        if diff >= m4_min_pct:
                            # РАСЧЕТ ПРИБЫЛИ
                            prof = (hb[t]['p'] * TAX_COEFF - o['price']) * min(o['volume_remain'], hb[t]['q'])
                            if prof > 0:
                                res_l.append([t, o['system_id'], o['volume_remain'], o['price'], hb[t]['p'], hb[t]['q'], hb[t]['h'], diff, prof])
                if len(d) < 1000: break
            bar.progress(5 + (i+1)*10)
        
        if res_l:
            st_txt.text("Синхронизация названий...")
            get_names_batch([x[0] for x in res_l] + [x[1] for x in res_l])
            df_m4 = pd.DataFrame(res_l, columns=["tid", "sid", "Кол S", "Цена Sell", "Цена Buy Хаб", "Кол B", "Целевой Хаб", "Профит %", "Прибыль ISK"])
            df_m4["Товар"] = df_m4["tid"].apply(lambda x: st.session_state.cache_name.get(str(x), str(x)))
            df_m4["Система"] = df_m4["sid"].apply(lambda x: st.session_state.cache_name.get(str(x), str(x)))
            st.dataframe(df_m4[["Товар", "Система", "Кол S", "Цена Sell", "Цена Buy Хаб", "Кол B", "Целевой Хаб", "Профит %", "Прибыль ISK"]].sort_values("Прибыль ISK", ascending=False), use_container_width=True)
            st_txt.text("Готово!")
        else: st.info("Сделок не найдено.")
        bar.progress(100)
