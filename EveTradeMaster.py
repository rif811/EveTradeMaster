import streamlit as st
import requests
import json
import os
import math
import pandas as pd
import urllib3

# --- КОНФИГУРАЦИЯ ---
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Налог с продаж (Accounting skill)
TAX_COEFF = 0.954  # 100% - 4.6%

# Группировка ресурсов для модуля "Чертежи"
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

# --- КЭШИРОВАНИЕ ---
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
if 'cache_sec' not in st.session_state: st.session_state.cache_sec = load_json("security_cache.json")

DB_PATH = "blueprints_db"
if not os.path.exists(DB_PATH): os.makedirs(DB_PATH)

# --- API ФУНКЦИИ ---
def get_id(name):
    n = name.strip().lower().replace('*', '')
    if n in st.session_state.id_map: return st.session_state.id_map[n]
    try:
        r = requests.post("https://esi.evetech.net/latest/universe/ids/", json=[n], timeout=10)
        if r.status_code == 200:
            data = r.json()
            if 'inventory_types' in data:
                tid = data['inventory_types'][0]['id']
                st.session_state.id_map[n] = tid
                st.session_state.cache_name[str(tid)] = data['inventory_types'][0]['name']
                save_json("id_map.json", st.session_state.id_map)
                save_json("names_db.json", st.session_state.cache_name)
                return tid
    except: pass
    return None

def get_names_batch(ids):
    to_f = [int(tid) for tid in ids if tid is not None and str(tid) not in st.session_state.cache_name]
    if to_f:
        try:
            for i in range(0, len(to_f), 1000):
                chunk = to_f[i:i+1000]
                r = requests.post("https://esi.evetech.net/latest/universe/names/", json=chunk, timeout=20).json()
                for item in r: st.session_state.cache_name[str(item['id'])] = item['name']
            save_json("names_db.json", st.session_state.cache_name)
        except: pass
    return st.session_state.cache_name

def get_security_status(system_id):
    sid = str(system_id)
    if sid in st.session_state.cache_sec: return st.session_state.cache_sec[sid]
    try:
        r = requests.get(f"https://esi.evetech.net/latest/universe/systems/{system_id}/").json()
        sec = r.get('security_status', 0)
        st.session_state.cache_sec[sid] = sec
        save_json("security_cache.json", st.session_state.cache_sec)
        return sec
    except: return 0

def fetch_recipe(tid):
    fp = os.path.join(DB_PATH, f"{tid}.txt")
    if os.path.exists(fp):
        try:
            with open(fp, "r") as f: d = json.load(f); return d['mats'], d['yld']
        except: pass
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
                if mats:
                    with open(fp, "w") as f: json.dump({'mats': mats, 'yld': yld}, f)
                    return mats, yld
    except: pass
    return None, 0

def get_bom_logic(name, needed, summary, stock, depth=0):
    if depth > 15: return
    name = name.strip()
    if name.lower() in BASE_RESOURCES_SET:
        summary[name] = summary.get(name, 0) + needed
        return
    in_stock = stock.get(name, 0.0)
    if in_stock >= needed:
        stock[name] -= needed
        return
    to_p = needed - in_stock
    stock[name] = 0.0
    tid = get_id(f"{name} Blueprint") or get_id(f"{name} Reaction Formula") or get_id(name)
    mats, yld = fetch_recipe(tid) if tid else (None, 0)
    if not mats or yld <= 0:
        summary[name] = summary.get(name, 0) + to_p
        return
    runs = math.ceil(to_p / yld)
    stock[name] = stock.get(name, 0.0) + (runs * yld - to_p)
    get_names_batch([m['typeid'] for m in mats])
    for m in mats:
        mname = st.session_state.cache_name.get(str(m['typeid']), str(m['typeid']))
        mqty = float(m['quantity']) * runs
        if mname.lower() != name.lower(): get_bom_logic(mname, mqty, summary, stock, depth + 1)

# --- ИНТЕРФЕЙС ---
st.set_page_config(page_title="EVE Master v13.0", layout="wide")
st.title("🛰️ EVE Online Master: Trade & Industry")

t1, t2, t3, t4 = st.tabs(["Арбитраж", "Срез цен", "Чертежи", "Глобальный поиск"])

# --- TAB 1 ---
with t1:
    c1, c2, c3 = st.columns(3)
    with c1: f_hub = st.selectbox("Из системы (Sell)", list(HUBS.keys()), index=0, key="m1f")
    with c2: t_hub = st.selectbox("В хаб (Buy)", list(HUBS.keys()), index=1, key="m1t")
    with c3: m1_pct = st.number_input("Мин. %", 1, 1000, 40, key="m1p")
    if st.button("Запустить Арбитраж"):
        h1, h2 = HUBS[f_hub], HUBS[t_hub]
        with st.spinner("Анализ..."):
            s_data = {}
            for p in range(1, 15):
                d = requests.get(f"https://esi.evetech.net/latest/markets/{h1['region_id']}/orders/", params={'order_type': 'sell', 'page': p}).json()
                if not d or 'error' in d: break
                for o in d:
                    if o['location_id'] == h1['station_id']:
                        tid = o['type_id']
                        if tid not in s_data or o['price'] < s_data[tid]['p']: s_data[tid] = {'p': o['price'], 'q': o['volume_remain']}
                if len(d) < 1000: break
            b_data = {}
            for p in range(1, 15):
                d = requests.get(f"https://esi.evetech.net/latest/markets/{h2['region_id']}/orders/", params={'order_type': 'buy', 'page': p}).json()
                if not d or 'error' in d: break
                for o in d:
                    if o['location_id'] == h2['station_id']:
                        tid = o['type_id']
                        if tid in s_data:
                            if tid not in b_data or o['price'] > b_data[tid]['p']: b_data[tid] = {'p': o['price'], 'q': o['volume_remain']}
            res = []
            for tid, b in b_data.items():
                s = s_data[tid]
                diff = ((b['p'] - s['p'])/s['p'])*100
                if diff >= m1_pct:
                    prof = (b['p'] * TAX_COEFF - s['p']) * min(s['q'], b['q'])
                    if prof > 0: res.append([tid, s['p'], s['q'], b['p'], b['q'], diff, prof])
            if res:
                get_names_batch([x[0] for x in res])
                df = pd.DataFrame(res, columns=["id", "Цена Sell", "Кол S", "Цена Buy", "Кол B", "Профит %", "Прибыль ISK"])
                df["Товар"] = df["id"].apply(lambda x: st.session_state.cache_name.get(str(x), str(x)))
                st.dataframe(df[["Товар", "Цена Sell", "Кол S", "Цена Buy", "Кол B", "Профит %", "Прибыль ISK"]].sort_values("Профит %", ascending=False), use_container_width=True)

# --- TAB 2 ---
with t2:
    it_n = st.text_input("Предмет", "Tritanium")
    if st.button("Показать цены"):
        it_id = get_id(it_n)
        if it_id:
            cols = st.columns(5)
            for i, (name, info) in enumerate(HUBS.items()):
                with cols[i]:
                    st.markdown(f"**{name}**")
                    r = requests.get(f"https://esi.evetech.net/latest/markets/{info['region_id']}/orders/", params={'order_type': 'sell', 'type_id': it_id}).json()
                    f = sorted([o for o in r if o['location_id'] == info['station_id']], key=lambda x: x['price'])[:3]
                    for o in f: st.write(f"{o['price']:,.2f} ISK")

# --- TAB 3 ---
with t3:
    bp_n = st.text_input("Чертеж", "Claymore")
    if st.button("Анализ"):
        sm, sk = {}, {}
        with st.spinner("Считаю..."): get_bom_logic(bp_n, 1.0, sm, sk)
        if sm:
            for grp, mbs in RESOURCE_GROUPS.items():
                fd = [[k, f"{int(v):,}"] for k, v in sm.items() if k in mbs]
                if fd:
                    st.subheader(grp)
                    st.table(pd.DataFrame(fd, columns=["Ресурс", "Всего"]))

# --- TAB 4 (ГЛОБАЛЬНЫЙ ПОИСК) ---
with t4:
    m4_pct = st.slider("Минимальный % профита", 10, 100, 40)
    if st.button("Начать Глобальный скан High-Sec"):
        bar = st.progress(0); st_txt = st.empty()
        hb = {}
        for i, (hn, info) in enumerate(HUBS.items()):
            st_txt.text(f"Хаб {hn}: сбор бай-ордеров...")
            d = requests.get(f"https://esi.evetech.net/latest/markets/{info['region_id']}/orders/", params={'order_type': 'buy'}).json()
            for o in d:
                if o['system_id'] == info['system_id']:
                    t = o['type_id']
                    if t not in hb or o['price'] > hb[t]['p']: hb[t] = {'p': o['price'], 'h': hn, 'q': o['volume_remain']}
            bar.progress((i+1)*5 // 140)
        
        res_l = []
        for i, (rid, rname) in enumerate(HIGHSEC_REGIONS.items()):
            st_txt.text(f"Регион {rname}: сканирование...")
            for p in range(1, 12):
                d = requests.get(f"https://esi.evetech.net/latest/markets/{rid}/orders/", params={'order_type': 'sell', 'page': p}).json()
                if not d or 'error' in d: break
                for o in d:
                    t = o['type_id']
                    if t in hb:
                        # ПРОВЕРКА БЕЗОПАСНОСТИ СИСТЕМЫ (Фильтр 0.5+)
                        if get_security_status(o['system_id']) >= 0.45:
                            diff = ((hb[t]['p'] - o['price'])/o['price'])*100
                            if diff >= m4_pct:
                                prf = (hb[t]['p'] * TAX_COEFF - o['price']) * min(o['volume_remain'], hb[t]['q'])
                                if prf > 0: res_l.append([t, o['system_id'], o['volume_remain'], o['price'], hb[t]['p'], hb[t]['q'], hb[t]['h'], diff, prf])
                if len(d) < 1000: break
            bar.progress(5 + (i+1)*10)

        if res_l:
            st_txt.text("Загрузка названий...")
            ids_all = [x[0] for x in res_l] + [x[1] for x in res_l]
            get_names_batch(ids_all) # ПРИНУДИТЕЛЬНЫЙ РЕЗОЛВ ИМЕН
            
            final_df = pd.DataFrame(res_l, columns=["tid", "sid", "Кол S", "Цена Sell", "Цена Buy Хаб", "Кол B", "Хаб", "Профит %", "Прибыль ISK"])
            final_df["Товар"] = final_df["tid"].apply(lambda x: st.session_state.cache_name.get(str(x), str(x)))
            final_df["Система"] = final_df["sid"].apply(lambda x: st.session_state.cache_name.get(str(x), str(x)))
            
            st.dataframe(final_df[["Товар", "Система", "Кол S", "Цена Sell", "Цена Buy Хаб", "Кол B", "Хаб", "Профит %", "Прибыль ISK"]].sort_values("Прибыль ISK", ascending=False), use_container_width=True)
            st_txt.text("Готово!")
        else: st.info("Нет сделок.")
        bar.progress(100)
