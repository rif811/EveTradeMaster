import streamlit as st
import requests
import json
import os
import math
import pandas as pd
import urllib3

# --- НАСТРОЙКИ ---
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

COLOR_SUCCESS = "#2ecc71"
COLOR_WORKING = "#f39c12"
COLOR_ERROR   = "#e74c3c"

# Группировка ресурсов для сводки (Чертежи)
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
    """Метод пакетной загрузки имен."""
    ids_to_fetch = list(set([int(tid) for tid in ids if str(tid) not in st.session_state.cache_name]))
    if ids_to_fetch:
        try:
            for i in range(0, len(ids_to_fetch), 1000):
                chunk = ids_to_fetch[i:i+1000]
                r = requests.post("https://esi.evetech.net/latest/universe/names/", json=chunk, timeout=20).json()
                for item in r: 
                    st.session_state.cache_name[str(item['id'])] = item['name']
            save_json_persistent("names_db.json", st.session_state.cache_name)
        except: pass
    return st.session_state.cache_name

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
    
    # Пытаемся найти чертеж
    tid = get_id(f"{name} Blueprint") or get_id(f"{name} Reaction Formula") or get_id(name)
    mats, yld = fetch_recipe(tid) if tid else (None, 0)
    
    if not mats or yld <= 0:
        summary[name] = summary.get(name, 0) + to_produce
        return

    runs = math.ceil(to_produce / yld)
    stock[name] = stock.get(name, 0.0) + (runs * yld - to_produce)
    
    # Загружаем имена компонентов заранее
    get_names_batch([m['typeid'] for m in mats])
    
    for m in mats:
        mname = st.session_state.cache_name.get(str(m['typeid']), str(m['typeid']))
        mqty = float(m['quantity']) * runs
        if mname.lower() != name.lower():
            get_bom_logic(mname, mqty, summary, stock, depth + 1)

# --- ИНТЕРФЕЙС ---
st.set_page_config(page_title="EVE Industry Master Web", layout="wide")
st.title("🛰️ EVE Online: Industry & Global Trade Master")

t1, t2, t3, t4 = st.tabs(["Арбитраж", "Срез цен", "Чертежи", "Глобальный поиск"])

# --- TAB 1: Арбитраж ---
with t1:
    c1, c2, c3 = st.columns(3)
    with c1: f_hub = st.selectbox("Из хаба (Sell)", list(HUBS.keys()), index=0, key="m1_from")
    with c2: t_hub = st.selectbox("В хаб (Buy)", list(HUBS.keys()), index=1, key="m1_to")
    with c3: pct_val = st.number_input("Мин. % профита", 1, 1000, 40, key="m1_pct")
    
    if st.button("Поиск Арбитража"):
        h1, h2 = HUBS[f_hub], HUBS[t_hub]
        with st.spinner("Загрузка рынков..."):
            # Sell data
            s_data = {}
            for p in range(1, 15):
                d = requests.get(f"https://esi.evetech.net/latest/markets/{h1['region_id']}/orders/", params={'order_type': 'sell', 'page': p}).json()
                if not d or 'error' in d: break
                for o in d:
                    if o['location_id'] == h1['station_id']:
                        tid = o['type_id']
                        if tid not in s_data or o['price'] < s_data[tid]['p']: s_data[tid] = {'p': o['price'], 'q': o['volume_remain']}
                if len(d) < 1000: break
            
            # Buy data
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
            
            final_res = []
            for tid, b in b_data.items():
                s = s_data[tid]
                diff = ((b['p'] - s['p'])/s['p'])*100
                if diff >= pct_val:
                    final_res.append([tid, s['p'], s['q'], b['p'], b['q'], diff])
            
            if final_res:
                get_names_batch([x[0] for x in final_res])
                table_data = []
                for r in final_res:
                    name = st.session_state.cache_name.get(str(r[0]), str(r[0]))
                    table_data.append([name, f"{r[1]:,.2f}", r[2], f"{r[3]:,.2f}", r[4], f"{r[5]:,.1f}%"])
                st.dataframe(pd.DataFrame(table_data, columns=["Товар", "Цена Sell", "Кол Sell", "Цена Buy", "Кол Buy", "Профит %"]), use_container_width=True)
            else: st.info("Выгодных сделок не найдено.")

# --- TAB 2: Срез цен ---
with t2:
    item_n = st.text_input("Название предмета", "Tritanium")
    if st.button("Показать цены хабов"):
        it_id = get_id(item_n)
        if it_id:
            cols = st.columns(5)
            for i, (name, info) in enumerate(HUBS.items()):
                with cols[i]:
                    st.markdown(f"**{name}**")
                    r = requests.get(f"https://esi.evetech.net/latest/markets/{info['region_id']}/orders/", params={'order_type': 'sell', 'type_id': it_id}).json()
                    f = sorted([o for o in r if o['location_id'] == info['station_id']], key=lambda x: x['price'])[:3]
                    for o in f: st.write(f"{o['price']:,.2f} ISK")
        else: st.error("Предмет не найден.")

# --- TAB 3: Чертежи ---
with t3:
    bp_q = st.text_input("Название чертежа", "Claymore")
    if st.button("Глубокий анализ"):
        sum_m, stock_m = {}, {}
        with st.spinner("Расчет иерархии..."):
            get_bom_logic(bp_q, 1.0, sum_m, stock_m)
        if sum_m:
            for group, members in RESOURCE_GROUPS.items():
                filtered = [[k, f"{int(v):,}"] for k, v in sum_m.items() if k in members]
                if filtered:
                    st.subheader(group)
                    st.table(pd.DataFrame(filtered, columns=["Ресурс", "Всего"]))
        else: st.error("Рецепт не найден.")

# --- TAB 4: Глобальный поиск ---
with t4:
    m4_pct = st.slider("Мин. профит %", 10, 100, 40, key="m4_pct_slider")
    if st.button("Начать Глобальный скан"):
        bar = st.progress(0)
        status = st.empty()
        
        hb_buys = {}
        # Сбор хабов
        for i, (hn, info) in enumerate(HUBS.items()):
            bar.progress((i+1)*5 // 14)
            status.text(f"Хаб {hn}: сбор данных...")
            d = requests.get(f"https://esi.evetech.net/latest/markets/{info['region_id']}/orders/", params={'order_type': 'buy'}).json()
            for o in d:
                if o['system_id'] == info['system_id']:
                    tid = o['type_id']
                    if tid not in hb_buys or o['price'] > hb_buys[tid]['p']: hb_buys[tid] = {'p': o['price'], 'h': hn}
        
        res_list = []
        # Сбор регионов
        for i, (rid, rname) in enumerate(HIGHSEC_REGIONS.items()):
            bar.progress(5 + (i+1)*10)
            status.text(f"Регион {rname}: сканирование...")
            for p in range(1, 10):
                d = requests.get(f"https://esi.evetech.net/latest/markets/{rid}/orders/", params={'order_type': 'sell', 'page': p}).json()
                if not d or 'error' in d: break
                for o in d:
                    tid = o['type_id']
                    if tid in hb_buys:
                        diff = ((hb_buys[tid]['p'] - o['price'])/o['price'])*100
                        if diff >= m4_pct:
                            res_list.append([tid, o['system_id'], o['volume_remain'], o['price'], hb_buys[tid]['p'], hb_buys[tid]['h'], diff])
                if len(d) < 1000: break
        
        if res_list:
            status.text("Загрузка названий...")
            # СОБИРАЕМ ВСЕ ID (товары + системы)
            ids_to_resolve = []
            for row in res_list:
                ids_to_resolve.append(row[0]) # Товар
                ids_to_resolve.append(row[1]) # Система
            
            # ПРИНУДИТЕЛЬНЫЙ ПЕРЕВОД В ИМЕНА
            get_names_batch(ids_to_resolve)
            
            final_table = []
            for r in res_list:
                item_name = st.session_state.cache_name.get(str(r[0]), str(r[0]))
                sys_name = st.session_state.cache_name.get(str(r[1]), str(r[1]))
                final_table.append([item_name, sys_name, r[2], f"{r[3]:,.2f}", f"{r[4]:,.2f}", r[5], f"{r[6]:.1f}%"])
            
            df = pd.DataFrame(final_table, columns=["Товар", "Система", "Кол-во", "Sell", "Buy Хаб", "Хаб", "%"])
            st.dataframe(df.sort_values("%", ascending=False), use_container_width=True)
            status.text("Готово!")
        else:
            st.info("Ничего не найдено.")
            status.text("Поиск завершен.")
        bar.progress(100)
