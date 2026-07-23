import streamlit as st
import requests
import json
import os
import math
import pandas as pd
from datetime import datetime
import urllib3

# Настройки
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Константы
COLOR_SUCCESS = "#2ecc71"
COLOR_WORKING = "#f39c12"
COLOR_ERROR   = "#e74c3c"

RESOURCE_GROUPS = {
    "Минералы": ["Tritanium", "Pyerite", "Mexallon", "Isogen", "Nocxium", "Zydrine", "Megacyte", "Morphite"],
    "Планетарка": ["Coolant", "Construction Blocks", "Consumer Electronics", "Enriched Uranium", "Robotics", "Mechanical Parts"],
    "Топливо": ["Nitrogen Isotopes", "Hydrogen Isotopes", "Helium Isotopes", "Oxygen Isotopes", "Liquid Ozone", "Heavy Water"],
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

# --- Инициализация состояния ---
if 'id_map' not in st.session_state:
    if os.path.exists("id_map.json"):
        with open("id_map.json", "r") as f: st.session_state.id_map = json.load(f)
    else: st.session_state.id_map = {}

if 'cache_name' not in st.session_state:
    if os.path.exists("names_db.json"):
        with open("names_db.json", "r") as f: st.session_state.cache_name = json.load(f)
    else: st.session_state.cache_name = {}

# Папка для рецептов
DB_PATH = "blueprints_db"
if not os.path.exists(DB_PATH): os.makedirs(DB_PATH)

# --- ФУНКЦИИ ЛОГИКИ ---

def get_id(name):
    n_low = name.strip().lower()
    if n_low in st.session_state.id_map: return st.session_state.id_map[n_low]
    try:
        r = requests.post("https://esi.evetech.net/latest/universe/ids/", json=[name.strip()], timeout=10)
        if r.status_code == 200:
            data = r.json()
            if 'inventory_types' in data:
                tid = data['inventory_types'][0]['id']
                st.session_state.id_map[n_low] = tid
                st.session_state.cache_name[str(tid)] = data['inventory_types'][0]['name']
                return tid
    except: pass
    return None

def get_names_batch(ids):
    to_fetch = [int(tid) for tid in ids if str(tid) not in st.session_state.cache_name]
    if to_fetch:
        try:
            for i in range(0, len(to_fetch), 1000):
                chunk = to_fetch[i:i+1000]
                r = requests.post("https://esi.evetech.net/latest/universe/names/", json=chunk, timeout=10).json()
                for item in r: st.session_state.cache_name[str(item['id'])] = item['name']
        except: pass
    return st.session_state.cache_name

def fetch_recipe(tid):
    fp = os.path.join(DB_PATH, f"{tid}.txt")
    if os.path.exists(fp):
        with open(fp, "r") as f: d = json.load(f); return d['mats'], d['yld']
    try:
        r = requests.get(f"https://www.fuzzwork.co.uk/blueprint/api/blueprint.php?typeid={tid}", timeout=10, verify=False).json()
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

def get_bom_logic(name, needed, final_summary, surplus_stock, depth=0):
    if depth > 15: return
    cn = name.strip()
    if cn.lower() in BASE_RESOURCES_SET:
        final_summary[cn] = final_summary.get(cn, 0) + needed
        return
    
    stock = surplus_stock.get(cn, 0.0)
    if stock >= needed:
        surplus_stock[cn] -= needed
        return
    
    to_p = needed - stock
    surplus_stock[cn] = 0.0
    
    tid = get_id(f"{cn} Blueprint") or get_id(cn)
    mats, yld = fetch_recipe(tid) if tid else (None, 0)
    
    if not mats or yld <= 0:
        final_summary[cn] = final_summary.get(cn, 0) + to_p
        return

    runs = math.ceil(to_p / yld)
    surplus_stock[cn] = surplus_stock.get(cn, 0) + (runs * yld - to_p)
    
    ids = [m['typeid'] for m in mats]
    get_names_batch(ids)
    
    for m in mats:
        mname = st.session_state.cache_name.get(str(m['typeid']), str(m['typeid']))
        mtot = float(m['quantity']) * runs
        if mname != name:
            get_bom_logic(mname, mtot, final_summary, surplus_stock, depth + 1)

# --- ИНТЕРФЕЙС STREAMLIT ---

st.set_page_config(page_title="EVE Industry Master Web", layout="wide")
st.title("🚀 EVE Online: Industry & Trade Master Web")

tab1, tab2, tab3, tab4 = st.tabs(["Межхабовая торговля", "Срез цен", "Чертежи", "Глобальный поиск"])

# --- TAB 1: Арбитраж ---
with tab1:
    col1, col2, col3 = st.columns(3)
    with col1: from_hub = st.selectbox("Из системы (Sell)", list(HUBS.keys()), index=0)
    with col2: to_hub = st.selectbox("В систему (Buy)", list(HUBS.keys()), index=1)
    with col3: min_profit = st.number_input("Мин. профит %", value=40)
    
    if st.button("Найти профит"):
        st.info("Загрузка данных рынка...")
        # (Тут должна быть логика fetch_market, сокращено для примера)
        st.warning("Модуль в разработке для веб-версии")

# --- TAB 3: Чертежи ---
with tab3:
    bp_name = st.text_input("Введите название чертежа (напр. Claymore)", "")
    if st.button("Рассчитать состав"):
        if bp_name:
            final_sum = {}
            surplus = {}
            with st.spinner(f"Анализируем {bp_name}..."):
                get_bom_logic(bp_name, 1.0, final_sum, surplus)
            
            if final_sum:
                st.success(f"Состав для {bp_name} готов!")
                # Отображение по группам
                for group, items in RESOURCE_GROUPS.items():
                    group_data = {k: v for k, v in final_sum.items() if k in items}
                    if group_data:
                        st.subheader(group)
                        df = pd.DataFrame(group_data.items(), columns=["Ресурс", "Количество"])
                        st.table(df)
            else:
                st.error("Чертеж не найден.")

# --- TAB 4: Глобальный поиск ---
with tab4:
    g_profit = st.slider("Минимальный профит %", 10, 100, 40)
    if st.button("Начать глобальное сканирование"):
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        # Логика Глобального поиска (упрощенно)
        status_text.text("Сбор данных из хабов...")
        progress_bar.progress(10)
        # ... (Код логики М4 из v12.0)
        status_text.text("Готово!")
        progress_bar.progress(100)
