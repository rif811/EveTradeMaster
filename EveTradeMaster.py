import streamlit as st
import requests
import json
import os
import math
import pandas as pd
import urllib3

# --- НАСТРОЙКИ ---
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Цвета
COLOR_SUCCESS = "#2ecc71"
COLOR_WORKING = "#f39c12"
COLOR_ERROR   = "#e74c3c"

# Группировка для сводки ресурсов (Чертежи)
RESOURCE_GROUPS = {
    "Минералы": ["Tritanium", "Pyerite", "Mexallon", "Isogen", "Nocxium", "Zydrine", "Megacyte", "Morphite"],
    "Планетарка": ["Coolant", "Construction Blocks", "Consumer Electronics", "Enriched Uranium", "Robotics", "Nanites", "Mechanical Parts"],
    "Топливо": ["Nitrogen Isotopes", "Hydrogen Isotopes", "Helium Isotopes", "Oxygen Isotopes", "Liquid Ozone", "Heavy Water", "Strontium Clathrates"],
    "Газы и Руды": ["Atmospheric Gases", "Evaporate Deposits", "Hydrocarbons", "Silicates", "Fullerite"]
}
BASE_RESOURCES_SET = {item.lower() for sublist in RESOURCE_GROUPS.values() for item in sublist}

# Регионы High-Sec
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

# --- ИНИЦИАЛИЗАЦИЯ СОСТОЯНИЯ ---
def load_json_persistent(filename):
    if os.path.exists(filename):
        try:
            with open(filename, "r", encoding="utf-8") as f: return json.load(f)
        except: return {}
    return {}

def save_json_persistent(filename, data):
    try:
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except: pass

if 'id_map' not in st.session_state:
    st.session_state.id_map = load_json_persistent("id_map.json")
if 'cache_name' not in st.session_state:
    st.session_state.cache_name = load_json_persistent("names_db.json")

DB_PATH = "blueprints_db"
if not os.path.exists(DB_PATH): os.makedirs(DB_PATH)

# --- API ФУНКЦИИ ---
def get_id(name):
    name = name.strip().lower().replace('*', '')
    if name in st.session_state.id_map: return st.session_state.id_map[name]
    try:
        r = requests.post("https://esi.evetech.net/latest/universe/ids/", json=[name], timeout=10)
        if r.status_code == 200:
            data = r.json()
            if 'inventory_types' in data:
                tid = data['inventory_types'][0]['id']
                st.session_state.id_map[name] = tid
                st.session_state.cache_name[str(tid)] = data['inventory_types'][0]['name']
                save_json_persistent("id_map.json", st.session_state.id_map)
                save_json_persistent("names_db.json", st.session_state.cache_name)
                return tid
    except: pass
    return None

def get_names_batch(ids):
    ids_to_fetch = [int(tid) for tid in ids if str(tid) not in st.session_state.cache_name]
    if ids_to_fetch:
        try:
            for i in range(0, len(ids_to_fetch), 1000):
                chunk = ids_to_fetch[i:i+1000]
                r = requests.post("https://esi.evetech.net/latest/universe/names/", json=chunk, timeout=15).json()
                for item in r: st.session_state.cache_name[str(item['id'])] = item['name']
            save_json_persistent("names_db.json", st.session_state.cache_name)
        except: pass
    return st.session_state.cache_name

def fetch_recipe(tid):
    fp = os.path.join(DB_PATH, f"{tid}.txt")
    if os.path.exists(fp):
        with open(fp, "r") as f: d = json.load(f); return d['mats'], d['yld']
    try:
        h = {'User-Agent': 'Mozilla/5.0'}
        r = requests.get(f"https://www.fuzzwork.co.uk/blueprint/api/blueprint.php?typeid={tid}", timeout=10, verify=False, headers=h).json()
        if 'activityMaterials' in r:
            am = r['activityMaterials']
            k = next((x for x in ['1','11'] if str(x) in am or x in am), next(iter(am.keys())) if am else None)
            if k:
                mats = am[str(k)] if str(k) in am else am[k]
                yld = int(r['activityProducts'][str(k)][0]['quantity']) if 'activityProducts' in r and str(k) in r['activityProducts'] else 1
                with open(fp, "w") as f: json.dump({'mats': mats, 'yld': yld}, f)
                return mats, yld
    except: pass
    return None, 0

def get_bom_logic(name, needed, summary, stock, depth=0):
    if depth > 12: return
    name = name.strip().replace('*','')
    if name.lower() in BASE_RESOURCES_SET:
        summary[name] = summary.get(name, 0) + needed
        return
    
    in_stock = stock.get(name, 0.0)
    if in_stock >= needed:
        stock[name] -= needed
        return
    
    to_produce = needed - in_stock
    stock[name] = 0.0
    
    tid = get_id(f"{name} Blueprint") or get_id(name)
    mats, yld = fetch_recipe(tid) if tid else (None, 0)
    
    if not mats or yld <= 0:
        summary[name] = summary.get(name, 0) + to_produce
        return

    runs = math.ceil(to_produce / yld)
    stock[name] = stock.get(name, 0.0) + (runs * yld - to_produce)
    
    mat_ids = [m['typeid'] for m in mats]
    get_names_batch(mat_ids)
    
    for m in mats:
        mname = st.session_state.cache_name.get(str(m['typeid']), str(m['typeid']))
        mqty = float(m['quantity']) * runs
        if mname.lower() != name.lower():
            get_bom_logic(mname, mqty, summary, stock, depth + 1)

# --- ИНТЕРФЕЙС ---

st.set_page_config(page_title="EVE Master Web", layout="wide")
st.title("🛰️ EVE Online: Industry & Trade Master")

tab1, tab2, tab3, tab4 = st.tabs(["Межхабовая торговля", "Срез цен", "Чертежи", "Глобальный поиск"])

# --- TAB 1: Арбитраж ---
with tab1:
    c1, c2, c3 = st.columns(3)
    with c1: f_hub = st.selectbox("Из хаба (Sell)", list(HUBS.keys()), index=0)
    with c2: t_hub = st.selectbox("В хаб (Buy)", list(HUBS.keys()), index=1)
    with c3: pct = st.number_input("Мин. % профита", 1, 1000, 40)
    
    if st.button("Запустить Арбитраж"):
        h1, h2 = HUBS[f_hub], HUBS[t_hub]
        with st.spinner("Сканирование рынков..."):
            # Sell
            s_data = {}
            for p in range(1, 10):
                d = requests.get(f"https://esi.evetech.net/latest/markets/{h1['region_id']}/orders/", params={'order_type': 'sell', 'page': p}).json()
                if not d or 'error' in d: break
                for o in d:
                    if o['location_id'] == h1['station_id']:
                        tid = o['type_id']
                        if tid not in s_data or o['price'] < s_data[tid]['p']: s_data[tid] = {'p': o['price'], 'q': o['volume_remain']}
            # Buy
            b_data = {}
            for p in range(1, 10):
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
                if diff >= pct:
                    res.append([tid, s['p'], s['q'], b['p'], b['q'], diff])
            
            if res:
                get_names_batch([x[0] for x in res])
                final_df = []
                for r in res:
                    final_df.append([st.session_state.cache_name.get(str(r[0]), r[0]), r[1], r[2], r[3], r[4], f"{r[5]:.1f}%"])
                df = pd.DataFrame(final_df, columns=["Товар", "Цена S1", "Кол S1", "Цена B2", "Кол B2", "Профит %"])
                st.dataframe(df.sort_values("Профит %", ascending=False), use_container_width=True)
            else: st.info("Сделок не найдено.")

# --- TAB 2: Срез цен ---
with tab2:
    item_query = st.text_input("Введите название товара для среза", "Tritanium")
    if st.button("Показать цены"):
        tid = get_id(item_query)
        if tid:
            cols = st.columns(5)
            for i, (hub_name, info) in enumerate(HUBS.items()):
                with cols[i]:
                    st.subheader(hub_name)
                    r = requests.get(f"https://esi.evetech.net/latest/markets/{info['region_id']}/orders/", params={'order_type': 'sell', 'type_id': tid}).json()
                    f = sorted([o for o in r if o['location_id'] == info['station_id']], key=lambda x: x['price'])[:3]
                    for o in f:
                        st.write(f"**{o['price']:,.2f}** ({o['volume_remain']:,} шт)")
        else: st.error("Товар не найден.")

# --- TAB 3: Чертежи ---
with tab3:
    bp_input = st.text_input("Название чертежа (напр. Claymore)", "")
    if st.button("Анализ состава"):
        summary, stock = {}, {}
        with st.spinner("Глубокий анализ..."):
            get_bom_logic(bp_input, 1.0, summary, stock)
        if summary:
            for grp, items in RESOURCE_GROUPS.items():
                g_data = [[k, f"{int(v):,}"] for k, v in summary.items() if k in items]
                if g_data:
                    st.subheader(grp)
                    st.table(pd.DataFrame(g_data, columns=["Материал", "Всего"]))
        else: st.error("Рецепт не найден.")

# --- TAB 4: Глобальный поиск ---
with tab4:
    g_pct = st.slider("Минимальный профит %", 10, 100, 40)
    if st.button("Начать Глобальное сканирование"):
        bar = st.progress(0)
        hb = {}
        # Хабы
        for i, (hn, info) in enumerate(HUBS.items()):
            bar.progress((i+1)*5 // 5)
            d = requests.get(f"https://esi.evetech.net/latest/markets/{info['region_id']}/orders/", params={'order_type': 'buy'}).json()
            for o in d:
                if o['system_id'] == info['system_id']:
                    t = o['type_id']
                    if t not in hb or o['price'] > hb[t]['p']: hb[t] = {'p': o['price'], 'h': hn}
        
        # Регионы
        res_l = []
        for i, (rid, rname) in enumerate(HIGHSEC_REGIONS.items()):
            bar.progress(5 + (i+1)*10)
            st.write(f"Сканирую {rname}...")
            for p in range(1, 10):
                d = requests.get(f"https://esi.evetech.net/latest/markets/{rid}/orders/", params={'order_type': 'sell', 'page': p}).json()
                if not d or 'error' in d: break
                for o in d:
                    t = o['type_id']
                    if t in hb:
                        diff = ((hb[t]['p'] - o['price'])/o['price'])*100
                        if diff >= g_pct:
                            prof = (hb[t]['p']*0.958 - o['price']) * o['volume_remain']
                            if prof > 0:
                                res_l.append([t, o['system_id'], o['volume_remain'], o['price'], hb[t]['p'], hb[t]['h'], diff, prof])
                if len(d) < 1000: break
        
        if res_l:
            all_ids = [x[0] for x in res_l] + [x[1] for x in res_l]
            get_names_batch(all_ids)
            f_data = []
            for r in res_l:
                f_data.append([st.session_state.cache_name.get(str(r[0]), r[0]), st.session_state.cache_name.get(str(r[1]), r[1]), r[2], r[3], r[4], r[5], f"{r[6]:.1f}%", f"{int(r[7]):,} ISK"])
            st.dataframe(pd.DataFrame(f_data, columns=["Товар", "Система", "Кол-во", "Sell", "Buy", "Хаб", "%", "Прибыль"]))
        else: st.info("Ничего не найдено.")
        bar.progress(100)
