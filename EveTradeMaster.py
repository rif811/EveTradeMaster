import tkinter as tk
from tkinter import ttk
import customtkinter as ctk
import requests
import threading
import logging
import urllib3
import os
import json
import math

# Настройки безопасности и логирования
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

COLOR_SUCCESS = "#2ecc71"
COLOR_WORKING = "#f39c12"
COLOR_ERROR   = "#e74c3c"
COLOR_INFO    = "#3498db"
COLOR_GRAY    = "#95a5a6"

# Группы ресурсов для модуля Чертежи (M3)
RESOURCE_GROUPS = {
    "Минералы": ["Tritanium", "Pyerite", "Mexallon", "Isogen", "Nocxium", "Zydrine", "Megacyte", "Morphite"],
    "Планетарка": ["Coolant", "Construction Blocks", "Consumer Electronics", "Enriched Uranium", "Robotics", "Nanites"],
    "Топливо": ["Nitrogen Isotopes", "Hydrogen Isotopes", "Helium Isotopes", "Oxygen Isotopes", "Liquid Ozone", "Heavy Water"],
    "Газы и Руды": ["Atmospheric Gases", "Evaporate Deposits", "Hydrocarbons", "Silicates", "Fullerite"],
    "Сальваг": ["Nanite Repair Paste", "R.A.M.- Robotics", "R.A.M.- Ship Tech"]
}
BASE_RESOURCES_SET = {item.lower() for sublist in RESOURCE_GROUPS.values() for item in sublist}

# Регионы для глобального поиска (M4)
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

class EveTradeMaster(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("EVE Online: Industry & Global Trade Master v13.0")
        self.geometry("1550x850")

        # --- Состояние данных (Персистентность) ---
        self.db_path = "blueprints_db"
        self.id_map_file = "id_map.json"
        self.names_db_file = "names_db.json"
        self.sec_cache_file = "security_cache.json"

        if not os.path.exists(self.db_path):
            os.makedirs(self.db_path)

        self.id_map = self.load_json(self.id_map_file)
        self.cache_name = self.load_json(self.names_db_file)
        self.cache_sec = self.load_json(self.sec_cache_file)
        self.cache_recipe = {}
        self.final_summary = {}
        self.surplus_stock = {}

        # --- Инициализация всех атрибутов виджетов (PEP8) ---
        self.m1_f = self.m1_t = self.m1_pct = self.m1_btn = self.m1_status = self.m1_tr = None
        self.m2_e = self.m2_b = self.m2_status = None
        self.m2_ts = {}
        self.m3_ent = self.m3_btn = self.m3_st = self.tr_bom = self.tr_sum = None
        self.m4_pct = self.m4_btn = self.m4_status = self.m4_tr = self.m4_progress = None

        self.setup_ui_styles()
        
        self.tabs = ctk.CTkTabview(self)
        self.tabs.pack(fill="both", expand=True, padx=10, pady=10)
        self.tab1 = self.tabs.add("Межхабовая торговля")
        self.tab2 = self.tabs.add("Лучшая цена продажи")
        self.tab3 = self.tabs.add("Чертежи")
        self.tab4 = self.tabs.add("Глобальный поиск")

        self.setup_m1()
        self.setup_m2()
        self.setup_m3()
        self.setup_m4()

    # --- СТАТИЧЕСКИЕ МЕТОДЫ УТИЛИТЫ ---
    @staticmethod
    def load_json(path):
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return {}
        return {}

    @staticmethod
    def save_json(path, data):
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
        except IOError:
            pass

    @staticmethod
    def clean_text(text):
        return text.strip().replace('*', '')

    @staticmethod
    def setup_ui_styles():
        style = ttk.Style()
        style.theme_use("default")
        style.configure("Treeview", background="#1d1e1e", foreground="white", fieldbackground="#1d1e1e", rowheight=25)
        style.map("Treeview", background=[('selected', '#1f538d')])

    def update_status_bar(self, widget, text, color=COLOR_GRAY):
        if widget:
            widget.configure(state="normal", text_color=color)
            widget.delete(0, tk.END)
            widget.insert(0, text)
            widget.configure(state="readonly")
            self.update_idletasks()

    def copy_to_clipboard(self, text):
        self.clipboard_clear()
        self.clipboard_append(text)

    def on_tree_click_copy(self, event, tree, status_widget, use_text=False):
        sel = tree.selection()
        if sel:
            try:
                # Если use_text=True, берем текст узла (#0), иначе первую колонку значений
                txt = tree.item(sel[0], "text") if use_text else tree.item(sel[0], "values")[0]
                if txt and txt not in RESOURCE_GROUPS:
                    self.copy_to_clipboard(txt)
                    self.update_status_bar(status_widget, f"Скопировано: {txt}", COLOR_INFO)
            except (IndexError, KeyError):
                pass

    def treeview_sort_column(self, tv, col, reverse):
        l_list = [(tv.set(k, col), k) for k in tv.get_children('')]
        def try_float(v):
            try: return float(v.replace(',', '').replace('%', '').replace(' ISK', ''))
            except ValueError: return v.lower()
        l_list.sort(key=lambda t: try_float(t[0]), reverse=reverse)
        for index, (_, k) in enumerate(l_list): tv.move(k, '', index)
        tv.heading(col, command=lambda: self.treeview_sort_column(tv, col, not reverse))

    def bind_copy_shortcuts(self, widget):
        """Обеспечивает работу Ctrl+C при любой раскладке."""
        def manual_copy(_):
            try:
                selected_text = widget.selection_get()
                self.copy_to_clipboard(selected_text)
            except: pass
            return "break"
        widget.bind("<Control-Key-c>", manual_copy)
        widget.bind("<Control-Key-C>", manual_copy)

    # --- API ФУНКЦИИ ---
    def get_id(self, name):
        n_low = name.strip().lower()
        if n_low in self.id_map: return self.id_map[n_low]
        try:
            resp = requests.post("https://esi.evetech.net/latest/universe/ids/", json=[name.strip()], timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if 'inventory_types' in data:
                    res_id = data['inventory_types'][0]['id']
                    res_name = data['inventory_types'][0]['name']
                    self.id_map[n_low] = res_id
                    self.cache_name[str(res_id)] = res_name
                    self.save_json(self.id_map_file, self.id_map)
                    self.save_json(self.names_db_file, self.cache_name)
                    return res_id
        except: pass
        return None

    def get_names_batch(self, ids):
        """Гарантирует загрузку всех имен перед выводом в таблицу."""
        # Очищаем список отNone и дублей, превращаем в int
        ids_to_fetch = list(set([int(tid) for tid in ids if tid is not None and str(tid) not in self.cache_name]))
        
        if ids_to_fetch:
            try:
                # Разбиваем на пачки по 1000 для ESI
                for i in range(0, len(ids_to_fetch), 1000):
                    chunk = ids_to_fetch[i:i+1000]
                    resp = requests.post("https://esi.evetech.net/latest/universe/names/", json=chunk, timeout=20)
                    if resp.status_code == 200:
                        for item in resp.json():
                            self.cache_name[str(item['id'])] = item['name']
                self.save_json(self.names_db_file, self.cache_name)
            except Exception as e:
                logging.error(f"Error in batch name fetch: {e}")
        return self.cache_name

    def get_security_status(self, system_id):
        sid_str = str(system_id)
        if sid_str in self.cache_sec: return self.cache_sec[sid_str]
        try:
            resp = requests.get(f"https://esi.evetech.net/latest/universe/systems/{system_id}/").json()
            sec = resp.get('security_status', 0)
            self.cache_sec[sid_str] = sec
            self.save_json(self.sec_cache_file, self.cache_sec)
            return sec
        except: return 0

    # --- МОДУЛЬ 1: АРБИТРАЖ ---
    def setup_m1(self):
        self.tab1.grid_columnconfigure(0, weight=1); self.tab1.grid_rowconfigure(2, weight=1)
        f = ctk.CTkFrame(self.tab1); f.grid(row=0, column=0, padx=20, pady=20, sticky="ew")
        self.m1_f = ctk.CTkComboBox(f, values=list(HUBS.keys()), width=160); self.m1_f.set("Jita"); self.m1_f.grid(row=0, column=0, padx=10)
        self.m1_t = ctk.CTkComboBox(f, values=list(HUBS.keys()), width=160); self.m1_t.set("Amarr"); self.m1_t.grid(row=0, column=1, padx=10)
        self.m1_pct = ctk.CTkEntry(f, width=70); self.m1_pct.insert(0, "40"); self.m1_pct.grid(row=0, column=2, padx=10)
        self.m1_btn = ctk.CTkButton(f, text="Найти Арбитраж", command=lambda: threading.Thread(target=self.run_m1, daemon=True).start())
        self.m1_btn.grid(row=0, column=3, padx=10)
        self.m1_status = ctk.CTkEntry(self.tab1, height=28, fg_color="transparent", border_width=0, justify="center"); self.m1_status.grid(row=1, column=0, sticky="ew", padx=20); self.update_status_bar(self.m1_status, "Готов")
        self.bind_copy_shortcuts(self.m1_status)
        cols = ("name", "p1_sell", "q1_sell", "p2_buy", "q2_buy", "diff")
        self.m1_tr = ttk.Treeview(self.tab1, columns=cols, show="headings")
        for col in cols: self.m1_tr.heading(col, text=col, command=lambda c=col: self.treeview_sort_column(self.m1_tr, c, False))
        self.m1_tr.grid(row=2, column=0, padx=20, pady=20, sticky="nsew")
        self.m1_tr.bind("<ButtonRelease-1>", lambda e: self.on_tree_click_copy(e, self.m1_tr, self.m1_status))

    def run_m1(self):
        try:
            self.m1_btn.configure(state="disabled", text="СБОР..."); self.m1_tr.delete(*self.m1_tr.get_children())
            s1, s2 = self.m1_f.get(), self.m1_t.get()
            def res_m1(n):
                nc = self.clean_text(n)
                if nc in HUBS: return HUBS[nc]['system_id'], HUBS[nc]['region_id'], HUBS[nc]['station_id']
                sid = self.get_id(nc)
                r_e = requests.get(f"https://esi.evetech.net/latest/universe/systems/{sid}/").json()
                ce = requests.get(f"https://esi.evetech.net/latest/universe/constellations/{r_e['constellation_id']}/").json()
                return sid, ce['region_id'], None
            id1, r1, st1 = res_m1(s1); id2, r2, st2 = res_m1(s2)
            def fetch(rid, sid, stid, mode, fids=None):
                res = {}; p = 1
                while True:
                    self.update_status_bar(self.m1_status, f"Загрузка {mode} {sid} стр {p}", COLOR_WORKING)
                    d = requests.get(f"https://esi.evetech.net/latest/markets/{rid}/orders/", params={'order_type': mode, 'page': p}).json()
                    if not d: break
                    for o in d:
                        if (stid and o['location_id'] == stid) or (not stid and o['system_id'] == sid):
                            tid = o['type_id']
                            if fids and tid not in fids: continue
                            pr, q = o['price'], o['volume_remain']
                            if mode == 'sell':
                                if tid not in res or pr < res[tid]['p']: res[tid] = {'p': pr, 'q': q}
                                elif pr == res[tid]['p']: res[tid]['q'] += q
                            else:
                                if tid not in res or pr > res[tid]['p']: res[tid] = {'p': pr, 'q': q}
                                elif pr == res[tid]['p']: res[tid]['q'] += q
                    if len(d) < 1000: break
                    p += 1
                return res
            sd = fetch(r1, id1, st1, 'sell'); bd = fetch(r2, id2, st2, 'buy', set(sd.keys()))
            rl = []
            min_p = float(self.m1_pct.get())
            for tid_int, b_o in bd.items():
                s_o = sd[tid_int]; df = ((b_o['p'] - s_o['p'])/s_o['p'])*100
                if df >= min_p: rl.append({'id': tid_int, 'ps': s_o['p'], 'qs': s_o['q'], 'pb': b_o['p'], 'qb': b_o['q'], 'd': df})
            self.get_names_batch([x['id'] for x in rl])
            rl.sort(key=lambda x: x['d'], reverse=True)
            for r in rl:
                nm = self.cache_name.get(str(r['id']), str(r['id']))
                self.m1_tr.insert("", "end", values=(nm, f"{r['ps']:,.2f}", r['qs'], f"{r['pb']:,.2f}", r['qb'], f"{r['d']:.1f}%"))
            self.update_status_bar(self.m1_status, "Готово", COLOR_SUCCESS)
        except Exception as e: self.update_status_bar(self.m1_status, f"Ошибка: {e}", COLOR_ERROR)
        finally: self.m1_btn.configure(state="normal", text="Найти Арбитраж")

    # --- МОДУЛЬ 2: СРЕЗ ЦЕН ---
    def setup_m2(self):
        self.tab2.grid_columnconfigure(0, weight=1); f = ctk.CTkFrame(self.tab2); f.grid(row=0, column=0, padx=20, pady=20, sticky="ew")
        self.m2_e = ctk.CTkEntry(f, width=500); self.m2_e.grid(row=0, column=0, padx=10); self.m2_b = ctk.CTkButton(f, text="Срез цен", command=lambda: threading.Thread(target=self.run_m2, daemon=True).start()); self.m2_b.grid(row=0, column=1, padx=10)
        self.m2_status = ctk.CTkEntry(self.tab2, height=28, fg_color="transparent", border_width=0, justify="center"); self.m2_status.grid(row=1, column=0, sticky="ew", padx=20); self.update_status_bar(self.m2_status, "Готов")
        self.bind_copy_shortcuts(self.m2_status)
        hc = ctk.CTkFrame(self.tab2, fg_color="transparent"); hc.grid(row=2, column=0, sticky="nsew", padx=10)
        for i, hn in enumerate(HUBS.keys()):
            r, c = i // 3, i % 3; fr = ctk.CTkFrame(hc, border_width=1, border_color="#3d3d3d"); fr.grid(row=r, column=c, padx=5, pady=5, sticky="nsew")
            ctk.CTkLabel(fr, text=hn, font=("Arial", 14, "bold")).pack(); t = ttk.Treeview(fr, columns=("p","q"), show="headings", height=3); t.heading("p", text="Цена Sell"); t.heading("q", text="Кол-во"); t.column("p", width=110); t.pack(padx=5, pady=5, fill="both"); self.m2_ts[hn] = t

    def run_m2(self):
        n = self.clean_text(self.m2_e.get()); tid = self.get_id(n)
        if not tid: return
        self.update_status_bar(self.m2_status, "Загрузка...", COLOR_WORKING)
        for hn, i in HUBS.items():
            resp = requests.get(f"https://esi.evetech.net/latest/markets/{i['region_id']}/orders/", params={'order_type': 'sell', 'type_id': tid}).json()
            f_m2 = sorted([o for o in resp if o['location_id'] == i['station_id']], key=lambda x: x['price'])[:3]
            self.m2_ts[hn].delete(*self.m2_ts[hn].get_children())
            for o in f_m2: self.m2_ts[hn].insert("", "end", values=(f"{o['price']:,.2f}", f"{o['volume_remain']:,}"))
        self.update_status_bar(self.m2_status, "Готово", COLOR_SUCCESS)

    # --- МОДУЛЬ 3: ЧЕРТЕЖИ ---
    def setup_m3(self):
        self.tab3.grid_columnconfigure(0, weight=1); self.tab3.grid_rowconfigure(2, weight=1)
        f = ctk.CTkFrame(self.tab3); f.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
        self.m3_ent = ctk.CTkEntry(f, placeholder_text="Claymore, Epithal...", width=500); self.m3_ent.grid(row=0, column=0, padx=10, pady=10); self.m3_btn = ctk.CTkButton(f, text="АНАЛИЗ", command=lambda: threading.Thread(target=self.run_m3, daemon=True).start(), font=("Arial", 14, "bold")); self.m3_btn.grid(row=0, column=1, padx=10)
        self.m3_st = ctk.CTkEntry(self.tab3, height=28, fg_color="transparent", border_width=0, justify="center"); self.m3_st.grid(row=1, column=0, sticky="ew", padx=20); self.update_status_bar(self.m3_st, "База готова")
        self.bind_copy_shortcuts(self.m3_st)
        cnt = ctk.CTkFrame(self.tab3, fg_color="transparent"); cnt.grid(row=2, column=0, sticky="nsew", padx=10, pady=10); cnt.grid_columnconfigure(0, weight=3); cnt.grid_columnconfigure(1, weight=2); cnt.grid_rowconfigure(0, weight=1)
        t_fr = ctk.CTkFrame(cnt); t_fr.grid(row=0, column=0, sticky="nsew", padx=(0,5))
        self.tr_bom = ttk.Treeview(t_fr, columns=("qty",), show="tree headings"); self.tr_bom.heading("#0", text="ИЕРАРХИЯ"); self.tr_bom.heading("qty", text="Расход"); self.tr_bom.column("#0", width=400); self.tr_bom.pack(fill="both", expand=True, padx=5, pady=5); self.tr_bom.bind("<ButtonRelease-1>", lambda e: self.on_tree_click_copy(e, self.tr_bom, self.m3_st, True))
        l_fr = ctk.CTkFrame(cnt); l_fr.grid(row=0, column=1, sticky="nsew", padx=(5,0))
        self.tr_sum = ttk.Treeview(l_fr, columns=("t",), show="tree headings"); self.tr_sum.heading("#0", text="БАЗОВЫЕ РЕСУРСЫ"); self.tr_sum.heading("t", text="ИТОГО"); self.tr_sum.column("t", width=120, anchor="e"); self.tr_sum.pack(fill="both", expand=True, padx=5, pady=5); self.tr_sum.bind("<ButtonRelease-1>", lambda e: self.on_tree_click_copy(e, self.tr_sum, self.m3_st, True))

    def fetch_recipe(self, tid):
        if str(tid) in self.cache_recipe: return self.cache_recipe[str(tid)]
        fp = os.path.join(self.db_path, f"{tid}.txt"); fp_n = os.path.join(self.db_path, f"{tid}_none.txt")
        if os.path.exists(fp_n): return None, 0
        if os.path.exists(fp):
            with open(fp, "r", encoding="utf-8") as f: d = json.load(f); return d['mats'], d['yld']
        try:
            r = requests.get(f"https://www.fuzzwork.co.uk/blueprint/api/blueprint.php?typeid={tid}", timeout=10, verify=False).json()
            if 'activityMaterials' in r:
                am = r['activityMaterials']
                k = next((x for x in ['1','11'] if str(x) in am or x in am), next(iter(am.keys())) if am else None)
                if k:
                    mats = am[str(k)] if str(k) in am else am[k]
                    yld = int(r['activityProducts'][str(k)][0]['quantity']) if 'activityProducts' in r and str(k) in r['activityProducts'] else 1
                    if mats:
                        with open(fp, "w", encoding="utf-8") as f: json.dump({'mats': mats, 'yld': yld}, f)
                        return mats, yld
            with open(fp_n, "w", encoding="utf-8") as f: f.write("none")
        except: pass
        return None, 0

    def get_bom_logic(self, name, needed, depth=0):
        if depth > 15: return []
        cn = name.strip()
        if cn.lower() in BASE_RESOURCES_SET:
            self.final_summary[cn] = self.final_summary.get(cn, 0) + needed; return []
        stock = self.surplus_stock.get(cn, 0.0)
        if stock >= needed:
            self.surplus_stock[cn] -= needed; return []
        to_p = needed - stock; self.surplus_stock[cn] = 0.0
        self.update_status_bar(self.m3_st, f"Раскрываю: {cn}...", COLOR_WORKING)
        tid = self.get_id(f"{cn} Blueprint") or self.get_id(f"{cn} Reaction Formula") or self.get_id(cn)
        mats, yld = (self.fetch_recipe(tid) if tid else (None, 0))
        if not mats or yld <= 0: self.final_summary[cn] = self.final_summary.get(cn, 0) + to_p; return []
        runs = math.ceil(to_p / yld); self.surplus_stock[cn] = self.surplus_stock.get(cn, 0) + (runs * yld - to_p)
        res = []
        self.get_names_batch([m['typeid'] for m in mats])
        for m in mats:
            mname = self.cache_name.get(str(m['typeid']), str(m['typeid']))
            mtot = float(m['quantity']) * runs
            if mname == name: continue
            res.append({'name': mname, 'qty': mtot / needed if needed > 0 else 0, 'children': self.get_bom_logic(mname, mtot, depth + 1)})
        return res

    def render_bom(self, parent, data):
        for c in data:
            v = (f"{c['qty']:,.2f}",); n = self.tr_bom.insert(parent, "end", text=c['name'], values=v, open=False)
            if c['children']: self.render_bom(n, c['children'])

    def run_m3(self):
        try:
            n = self.clean_text(self.m3_ent.get()); self.m3_btn.configure(state="disabled")
            self.tr_bom.delete(*self.tr_bom.get_children()); self.tr_sum.delete(*self.tr_sum.get_children())
            self.final_summary = {}; self.surplus_stock = {}
            struct = self.get_bom_logic(n, 1.0)
            root = self.tr_bom.insert("", "end", text=n.upper(), values=("1",), open=True)
            self.render_bom(root, struct)
            for grp, mbs in RESOURCE_GROUPS.items():
                gd = {m: self.final_summary[m] for m in mbs if m in self.final_summary}
                if gd:
                    gn = self.tr_sum.insert("", "end", text=grp, open=True)
                    for mn, mq in sorted(gd.items()): self.tr_sum.insert(gn, "end", text=mn, values=(f"{int(mq):,}",))
            self.update_status_bar(self.m3_st, "Готово", COLOR_SUCCESS)
        except Exception as e: self.update_status_bar(self.m3_st, f"Ошибка: {e}", COLOR_ERROR)
        finally: self.m3_btn.configure(state="normal")

    # --- МОДУЛЬ 4: ГЛОБАЛЬНЫЙ ПОИСК ---
    def setup_m4(self):
        self.tab4.grid_columnconfigure(0, weight=1); self.tab4.grid_rowconfigure(2, weight=1)
        f = ctk.CTkFrame(self.tab4); f.grid(row=0, column=0, padx=20, pady=20, sticky="ew")
        ctk.CTkLabel(f, text="Мин %:").grid(row=0, column=0, padx=5)
        self.m4_pct = ctk.CTkEntry(f, width=60); self.m4_pct.insert(0, "40"); self.m4_pct.grid(row=0, column=1, padx=5)
        self.m4_btn = ctk.CTkButton(f, text="ГЛОБАЛЬНЫЙ СКАН", command=lambda: threading.Thread(target=self.run_m4, daemon=True).start())
        self.m4_btn.grid(row=0, column=2, padx=20)
        self.m4_status = ctk.CTkEntry(self.tab4, height=28, fg_color="transparent", border_width=0, justify="center"); self.m4_status.grid(row=1, column=0, sticky="ew", padx=20); self.update_status_bar(self.m4_status, "Готов")
        self.bind_copy_shortcuts(self.m4_status)
        self.m4_progress = ctk.CTkProgressBar(self.tab4, height=15); self.m4_progress.grid(row=3, column=0, sticky="ew", padx=20, pady=(0, 20)); self.m4_progress.set(0)
        cols = ("name", "system", "qty", "ps", "pb", "hub", "diff", "prof")
        self.m4_tr = ttk.Treeview(self.tab4, columns=cols, show="headings")
        tits = ["Товар", "Система", "Кол-во", "Цена Sell", "Цена Buy Хаб", "Хаб", "Профит %", "Прибыль ISK"]
        for i, col in enumerate(cols):
            self.m4_tr.heading(col, text=tits[i], command=lambda _c=col: self.treeview_sort_column(self.m4_tr, _c, False))
            self.m4_tr.column(col, width=130, anchor="center")
        self.m4_tr.grid(row=2, column=0, padx=20, pady=20, sticky="nsew")
        self.m4_tr.bind("<ButtonRelease-1>", lambda e: self.on_tree_click_copy(e, self.m4_tr, self.m4_status))

    def run_m4(self):
        try:
            self.m4_btn.configure(state="disabled"); self.m4_tr.delete(*self.m4_tr.get_children())
            self.m4_progress.set(0); min_p = float(self.m4_pct.get()); hb = {}
            total = len(HUBS) + len(HIGHSEC_REGIONS); curr = 0
            for hn, i in HUBS.items():
                curr += 1; self.m4_progress.set(curr / total)
                self.update_status_bar(self.m4_status, f"{int(curr/total*100)}% | Хаб {hn}: бай-ордера...", COLOR_WORKING)
                resp = requests.get(f"https://esi.evetech.net/latest/markets/{i['region_id']}/orders/", params={'order_type': 'buy'}).json()
                for o in resp:
                    if o['system_id'] == i['system_id']:
                        t_id = o['type_id']
                        if t_id not in hb or o['price'] > hb[t_id]['p']: hb[t_id] = {'p': o['price'], 'h': hn}
            res_l = []
            for rid, rname in HIGHSEC_REGIONS.items():
                curr += 1; self.m4_progress.set(curr / total)
                p = 1
                while True:
                    self.update_status_bar(self.m4_status, f"{int(curr/total*100)}% | Регион {rname}: стр {p}", COLOR_WORKING)
                    resp = requests.get(f"https://esi.evetech.net/latest/markets/{rid}/orders/", params={'order_type': 'sell', 'page': p}).json()
                    if not resp: break
                    for o in resp:
                        tid_m4 = o['type_id']
                        if tid_m4 in hb:
                            df = ((hb[tid_m4]['p'] - o['price']) / o['price']) * 100
                            if df >= min_p:
                                if self.get_security_status(o['system_id']) >= 0.45:
                                    prof = (hb[tid_m4]['p'] * 0.958 - o['price']) * o['volume_remain']
                                    if prof > 0: res_l.append({'id': tid_m4, 'sid': o['system_id'], 'q': o['volume_remain'], 'ps': o['price'], 'pb': hb[tid_m4]['p'], 'h': hb[tid_m4]['h'], 'd': df, 'pr': prof})
                    if len(resp) < 1000: break
                    p += 1
            # ВАЖНО: ЗАГРУЗКА ИМЕН ДЛЯ ВСЕХ НАЙДЕННЫХ ID
            self.update_status_bar(self.m4_status, "95% | Загрузка названий систем и товаров...", COLOR_WORKING)
            all_ids = []
            for r in res_l:
                all_ids.append(r['id'])
                all_ids.append(r['sid'])
            self.get_names_batch(all_ids)
            
            for r in res_l:
                nm = self.cache_name.get(str(r['id']), str(r['id']))
                sn = self.cache_name.get(str(r['sid']), str(r['sid']))
                self.m4_tr.insert("", "end", values=(nm, sn, f"{r['q']:,}", f"{r['ps']:,.2f}", f"{r['pb']:,.2f}", r['h'], f"{r['d']:.1f}%", f"{r['pr']:,.0f} ISK"))
            self.update_status_bar(self.m4_status, "Готово", COLOR_SUCCESS)
        except Exception as e: self.update_status_bar(self.m4_status, f"Ошибка: {e}", COLOR_ERROR)
        finally: self.m4_btn.configure(state="normal")

if __name__ == "__main__":
    EveTradeMaster().mainloop()