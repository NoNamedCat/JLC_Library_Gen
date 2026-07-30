import wx
import io
import json
import re
import requests
import urllib.request
import urllib.error
import urllib.parse
import ssl
import sys
import webbrowser
import os
import pcbnew
import shutil
import tempfile
import subprocess
import threading
import traceback
from datetime import datetime
from math import ceil
from .easyeda_renderer import EasyEDASymbolPanel, EasyEDAFootprintPanel
from .schematic_injector import SchematicInjector


CONFIG_FILE = os.path.join(os.path.dirname(__file__), "config.json")

def load_settings():
    defaults = {
        "lib_folder": "EasyEDA_Components",
        "window_size": [1300, 900],
        "splitter_pos": 750,
        "splitter_pos_v1": 450,
        "splitter_pos_v2": 300,
        "is_maximized": False,
        "colors": {
            "Background": "#141414", "SymbolBody": "#C83232", "Pin": "#C8C8C8",
            "PinName": "#32DCDC", "PinNum": "#DCDC32", "Copper": "#C85050",
            "Silk": "#FFFF64", "Fab": "#969696", "Pad": "#C8C896", "PadText": "#1E1E1E"
        }
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                saved = json.load(f)
                for k in ["lib_folder", "window_size", "splitter_pos", "splitter_pos_v1", "splitter_pos_v2", "is_maximized"]:
                    if k in saved: defaults[k] = saved[k]
                if "colors" in saved: defaults["colors"].update(saved["colors"])
        except: pass
    return defaults

def save_settings(settings):
    try:
        with open(CONFIG_FILE, "w") as f: json.dump(settings, f, indent=4)
    except: pass

class SettingsDialog(wx.Dialog):
    def __init__(self, parent, current_settings):
        super().__init__(parent, title="Plugin Settings", size=(400, 550))
        self.settings = current_settings
        sizer = wx.BoxSizer(wx.VERTICAL)
        grid = wx.FlexGridSizer(cols=2, vgap=10, hgap=10)
        self.pickers = {}
        for name, color in self.settings["colors"].items():
            grid.Add(wx.StaticText(self, label=f"{name}:"), 0, wx.ALIGN_CENTER_VERTICAL)
            picker = wx.ColourPickerCtrl(self, colour=wx.Colour(color))
            grid.Add(picker, 0, wx.EXPAND); self.pickers[name] = picker
        sizer.Add(grid, 1, wx.EXPAND | wx.ALL, 15)
        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        save_btn = wx.Button(self, label="Save"); save_btn.Bind(wx.EVT_BUTTON, self.on_save)
        cancel_btn = wx.Button(self, label="Cancel"); cancel_btn.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_CANCEL))
        btn_sizer.Add(save_btn); btn_sizer.Add(cancel_btn, 0, wx.LEFT, 10)
        sizer.Add(btn_sizer, 0, wx.ALIGN_RIGHT | wx.ALL, 15)
        self.SetSizer(sizer); self.Centre()
    def on_save(self, event):
        for name, picker in self.pickers.items():
            self.settings["colors"][name] = picker.GetColour().GetAsString(wx.C2S_HTML_SYNTAX)
        self.EndModal(wx.ID_OK)

class ImagePopupDialog(wx.Dialog):
    def __init__(self, parent, image_bytes, title):
        super().__init__(parent, title=title, style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        try:
            image = wx.Image(io.BytesIO(image_bytes)); bitmap = wx.Bitmap(image)
            self.static_bitmap = wx.StaticBitmap(self, wx.ID_ANY, bitmap)
            sizer = wx.BoxSizer(wx.VERTICAL); sizer.Add(self.static_bitmap, 1, wx.EXPAND | wx.ALL, 5)
            self.SetSizerAndFit(sizer); self.Centre()
        except: self.Destroy()

class RendererPopupDialog(wx.Dialog):
    def __init__(self, parent, data, mode, title, colors):
        super().__init__(parent, title=title, size=(800, 800), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        sizer = wx.BoxSizer(wx.VERTICAL)
        self.renderer = EasyEDASymbolPanel(self) if mode == 'symbol' else EasyEDAFootprintPanel(self)
        self.renderer.update_colors(colors); self.renderer.load_data(data)
        sizer.Add(self.renderer, 1, wx.EXPAND)
        self.SetSizer(sizer); self.Centre()

class LogConsoleDialog(wx.Dialog):
    def __init__(self, parent):
        super().__init__(parent, title="Debug Log", size=(700, 450), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.log_ctrl = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.HSCROLL)
        self.log_ctrl.SetBackgroundColour(wx.Colour(30, 30, 30)); self.log_ctrl.SetForegroundColour(wx.Colour(200, 200, 200))
        sizer = wx.BoxSizer(wx.VERTICAL); sizer.Add(self.log_ctrl, 1, wx.EXPAND | wx.ALL, 5)
        btn = wx.Button(self, label="Close"); btn.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_OK))
        sizer.Add(btn, 0, wx.ALIGN_RIGHT | wx.ALL, 10); self.SetSizer(sizer)

class ComponentImagePanel(wx.Panel):
    def __init__(self, parent):
        super().__init__(parent, style=wx.BORDER_SIMPLE | wx.FULL_REPAINT_ON_RESIZE)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.raw_image = None
        self.Bind(wx.EVT_PAINT, self.on_paint)
        
    def set_image_data(self, data):
        try:
            self.raw_image = wx.Image(io.BytesIO(data))
            self.Refresh()
        except: self.raw_image = None; self.Refresh()

    def clear(self):
        self.raw_image = None
        self.Refresh()

    def on_paint(self, event):
        dc = wx.AutoBufferedPaintDC(self)
        dc.SetBackground(wx.Brush(self.GetBackgroundColour()))
        dc.Clear()
        if not self.raw_image or not self.raw_image.IsOk(): return
        
        cw, ch = self.GetClientSize()
        if cw < 10 or ch < 10: return
        
        iw, ih = self.raw_image.GetWidth(), self.raw_image.GetHeight()
        scale = min(float(cw)/iw, float(ch)/ih)
        nw, nh = max(1, int(iw*scale)), max(1, int(ih*scale))
        
        scaled_img = self.raw_image.Scale(nw, nh, wx.IMAGE_QUALITY_HIGH)
        bmp = wx.Bitmap(scaled_img)
        dc.DrawBitmap(bmp, (cw-nw)//2, (ch-nh)//2)

class EasyEDASearchDialog(wx.Dialog):
    cached_cad_data = None
    def __init__(self, parent):
        self.settings = load_settings()
        super().__init__(parent, title="JLC Library Gen", size=tuple(self.settings["window_size"]), 
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER | wx.MAXIMIZE_BOX | wx.MINIMIZE_BOX)
        if self.settings.get("is_maximized"): self.Maximize()
        
        self.jlc_api = "https://jlcpcb.com/api/overseas-pcb-order/v1/shoppingCart/smtGood"
        self.session = requests.Session()
        self.xsrf_token = None
        self.injector = SchematicInjector(log_callback=self._log_to_console)
        self.products = []; self.cart_items = []; self.log_buffer = ""; self.current_keyword = ""; self.current_page = 1; self.total_pages = 1

        self.categories_map = {}; self.brands_map = {}
        self.sort_col = 0; self.sort_desc = False
        
        self.current_images = []; self.current_image_index = 0; self.cad_data = None; self.full_size_image_bytes = None
        self.preview_temp_dir = tempfile.TemporaryDirectory(prefix="easyeda_preview_")
        
        self._check_dependencies()

        self.main_splitter = wx.SplitterWindow(self, style=wx.SP_LIVE_UPDATE)
        
        # Left Side: Multi-Splitter Structure
        self.left_splitter_main = wx.SplitterWindow(self.main_splitter, style=wx.SP_LIVE_UPDATE)
        self.left_splitter_bottom = wx.SplitterWindow(self.left_splitter_main, style=wx.SP_LIVE_UPDATE)
        
        # Notebook for Search vs Global Library
        self.notebook = wx.Notebook(self.left_splitter_main)
        
        # 1. Search Panel (Tab 1)
        search_tab = wx.Panel(self.notebook)
        search_sizer = wx.BoxSizer(wx.VERTICAL)
        
        search_row = wx.BoxSizer(wx.HORIZONTAL)
        self.search_ctrl = wx.TextCtrl(search_tab, style=wx.TE_PROCESS_ENTER)
        self.search_btn = wx.Button(search_tab, label="Search")
        search_row.Add(self.search_ctrl, 1, wx.EXPAND | wx.ALL, 5); search_row.Add(self.search_btn, 0, wx.ALL, 5)
        search_sizer.Add(search_row, 0, wx.EXPAND)

        filter_row1 = wx.BoxSizer(wx.HORIZONTAL)
        self.stock_check = wx.CheckBox(search_tab, label="In Stock"); self.stock_check.SetValue(True)
        self.basic_check = wx.CheckBox(search_tab, label="BASIC ONLY"); self.basic_check.SetForegroundColour(wx.Colour(0, 150, 0))
        filter_row1.Add(self.stock_check, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT | wx.RIGHT, 10)
        filter_row1.Add(self.basic_check, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 15)
        filter_row1.Add(wx.StaticText(search_tab, label="Lib Folder:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        self.lib_folder_ctrl = wx.TextCtrl(search_tab, value=self.settings["lib_folder"], size=(120, -1))
        filter_row1.Add(self.lib_folder_ctrl, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
        search_sizer.Add(filter_row1, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        self.list = wx.ListCtrl(search_tab, style=wx.LC_REPORT | wx.BORDER_SUNKEN)
        self.list.InsertColumn(0, "Part", width=140); self.list.InsertColumn(1, "Package", width=100)
        self.list.InsertColumn(2, "Type", width=70); self.list.InsertColumn(3, "Stock", width=80)
        self.list.InsertColumn(4, "Price", width=70); self.list.InsertColumn(5, "Brand", width=120)
        self.list.InsertColumn(6, "LCSC #", width=80)
        search_sizer.Add(self.list, 1, wx.EXPAND | wx.ALL, 5)
        
        page_row = wx.BoxSizer(wx.HORIZONTAL)
        self.prev_btn, self.next_btn = wx.Button(search_tab, label="<", size=(40, -1)), wx.Button(search_tab, label=">", size=(40, -1))
        self.page_info = wx.StaticText(search_tab, label="Page 1/1")
        self.save_global_btn = wx.Button(search_tab, label="⭐ SAVE GLOBAL", size=(120, -1))
        self.add_to_cart_btn = wx.Button(search_tab, label="ADD TO LIST >>", size=(120, -1))
        self.add_to_cart_btn.SetForegroundColour(wx.Colour(0, 120, 0))
        page_row.Add(self.prev_btn, 0); page_row.Add(self.page_info, 0, wx.ALIGN_CENTER | wx.LEFT | wx.RIGHT, 15); page_row.Add(self.next_btn, 0)
        page_row.AddStretchSpacer(); page_row.Add(self.save_global_btn, 0, wx.RIGHT, 5); page_row.Add(self.add_to_cart_btn, 0, wx.RIGHT, 5)
        search_sizer.Add(page_row, 0, wx.EXPAND | wx.BOTTOM, 5); search_tab.SetSizer(search_sizer)

        # 1b. Global Library Tab
        global_tab = wx.Panel(self.notebook)
        global_sizer = wx.BoxSizer(wx.VERTICAL)
        
        global_search_row = wx.BoxSizer(wx.HORIZONTAL)
        global_search_row.Add(wx.StaticText(global_tab, label="Filter:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        self.global_filter_ctrl = wx.TextCtrl(global_tab)
        global_search_row.Add(self.global_filter_ctrl, 1, wx.EXPAND | wx.ALL, 5)
        global_sizer.Add(global_search_row, 0, wx.EXPAND)

        self.global_list = wx.ListCtrl(global_tab, style=wx.LC_REPORT | wx.BORDER_SUNKEN)
        self.global_list.InsertColumn(0, "Part", width=150); self.global_list.InsertColumn(1, "Package", width=100)
        self.global_list.InsertColumn(2, "Brand", width=120); self.global_list.InsertColumn(3, "LCSC #", width=100)
        global_sizer.Add(self.global_list, 1, wx.EXPAND | wx.ALL, 5)
        
        global_act_row = wx.BoxSizer(wx.HORIZONTAL)
        self.global_add_btn = wx.Button(global_tab, label="ADD TO LIST >>", size=(120, -1))
        self.global_remove_btn = wx.Button(global_tab, label="Delete from Global", size=(130, -1))
        self.global_remove_btn.SetForegroundColour(wx.RED)
        global_act_row.Add(self.global_add_btn, 0, wx.RIGHT, 10); global_act_row.AddStretchSpacer(); global_act_row.Add(self.global_remove_btn, 0, wx.RIGHT, 5)
        global_sizer.Add(global_act_row, 0, wx.EXPAND | wx.BOTTOM, 5); global_tab.SetSizer(global_sizer)

        self.notebook.AddPage(search_tab, "JLCPCB Search")
        self.notebook.AddPage(global_tab, "Global Library")

        # 2. Project Components Panel
        project_panel = wx.Panel(self.left_splitter_bottom)
        project_sizer = wx.BoxSizer(wx.VERTICAL)
        project_sizer.Add(wx.StaticText(project_panel, label="PROJECT COMPONENTS:"), 0, wx.LEFT | wx.TOP, 5)
        self.cart_list = wx.ListCtrl(project_panel, style=wx.LC_REPORT | wx.BORDER_SUNKEN)
        self.cart_list.InsertColumn(0, "Part", width=150); self.cart_list.InsertColumn(1, "Qty", width=50)
        self.cart_list.InsertColumn(2, "LCSC #", width=100); self.cart_list.InsertColumn(3, "Package", width=100)
        project_sizer.Add(self.cart_list, 1, wx.EXPAND | wx.ALL, 5)
        
        cart_btns = wx.BoxSizer(wx.HORIZONTAL)
        self.qty_up_btn = wx.Button(project_panel, label="+", size=(35, -1)); self.qty_down_btn = wx.Button(project_panel, label="-", size=(35, -1))
        self.remove_cart_btn = wx.Button(project_panel, label="Remove Selected", size=(120, -1))
        cart_btns.Add(self.qty_up_btn, 0, wx.RIGHT, 2); cart_btns.Add(self.qty_down_btn, 0, wx.RIGHT, 10); cart_btns.Add(self.remove_cart_btn, 0)
        project_sizer.Add(cart_btns, 0, wx.LEFT | wx.BOTTOM, 5); project_panel.SetSizer(project_sizer)

        # 3. Instance List Panel
        instance_panel = wx.Panel(self.left_splitter_bottom)
        instance_sizer = wx.BoxSizer(wx.VERTICAL)
        instance_sizer.Add(wx.StaticText(instance_panel, label="INSTANCES IN SCHEMATIC:"), 0, wx.LEFT | wx.TOP, 5)
        self.instance_list = wx.ListCtrl(instance_panel, style=wx.LC_REPORT | wx.BORDER_SUNKEN)
        self.instance_list.InsertColumn(0, "Ref", width=60); self.instance_list.InsertColumn(1, "UUID", width=250)
        instance_sizer.Add(self.instance_list, 1, wx.EXPAND | wx.ALL, 5)
        self.remove_inst_btn = wx.Button(instance_panel, label="Delete Inst", size=(100, -1))
        self.remove_inst_btn.SetForegroundColour(wx.RED)
        instance_sizer.Add(self.remove_inst_btn, 0, wx.LEFT | wx.BOTTOM, 5); instance_panel.SetSizer(instance_sizer)

        # Right Panel
        right_panel = wx.Panel(self.main_splitter)
        self.left_splitter_bottom.SplitHorizontally(project_panel, instance_panel, sashPosition=self.settings["splitter_pos_v2"])
        self.left_splitter_main.SplitHorizontally(self.notebook, self.left_splitter_bottom, sashPosition=self.settings["splitter_pos_v1"])
        self.main_splitter.SplitVertically(self.left_splitter_main, right_panel, sashPosition=self.settings["splitter_pos"])
        self.main_splitter.SetMinimumPaneSize(450)

        # Load existing components from project file
        self._load_project_components()
        self._update_global_list()

        right_panel_sizer = wx.BoxSizer(wx.VERTICAL)
        right_panel.SetSizer(right_panel_sizer)

        right_panel_sizer.Add(wx.StaticText(right_panel, label="PHOTO PREVIEW"), 0, wx.LEFT | wx.TOP, 5)
        self.image_ctrl = ComponentImagePanel(right_panel)
        right_panel_sizer.Add(self.image_ctrl, 1, wx.EXPAND | wx.ALL, 5)

        right_panel_sizer.Add(wx.StaticText(right_panel, label="SYMBOL (EASYEDA)"), 0, wx.LEFT, 5)
        self.symbol_preview = EasyEDASymbolPanel(right_panel); self.symbol_preview.SetWindowStyle(wx.BORDER_SIMPLE); self.symbol_preview.update_colors(self.settings["colors"])
        right_panel_sizer.Add(self.symbol_preview, 1, wx.EXPAND | wx.ALL, 5)

        right_panel_sizer.Add(wx.StaticText(right_panel, label="FOOTPRINT (EASYEDA)"), 0, wx.LEFT, 5)
        self.footprint_preview = EasyEDAFootprintPanel(right_panel); self.footprint_preview.SetWindowStyle(wx.BORDER_SIMPLE); self.footprint_preview.update_colors(self.settings["colors"])
        right_panel_sizer.Add(self.footprint_preview, 1, wx.EXPAND | wx.ALL, 5)

        right_panel_sizer.Add(wx.StaticText(right_panel, label="TECHNICAL PROPERTIES"), 0, wx.LEFT, 5)
        self.prop_list = wx.ListCtrl(right_panel, style=wx.LC_REPORT | wx.BORDER_SIMPLE)
        self.prop_list.InsertColumn(0, "Attribute", width=150); self.prop_list.InsertColumn(1, "Value", width=180)
        right_panel_sizer.Add(self.prop_list, 1, wx.EXPAND | wx.ALL, 5)

        info_panel = wx.Panel(right_panel); info_sizer = wx.BoxSizer(wx.VERTICAL)
        self.title_text = wx.StaticText(info_panel, label="Select a component"); self.title_text.SetFont(wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        info_sizer.Add(self.title_text, 0, wx.ALL, 5); self.cad_status_text = wx.StaticText(info_panel, label="CAD Status: Unknown"); info_sizer.Add(self.cad_status_text, 0, wx.LEFT, 5)
        act_row = wx.BoxSizer(wx.HORIZONTAL)
        self.datasheet_btn, self.download_btn = wx.Button(info_panel, label="View PDF"), wx.Button(info_panel, label="ADD CART TO PROJECT")
        self.download_btn.SetBackgroundColour(wx.Colour(0, 150, 0)); self.download_btn.SetForegroundColour(wx.WHITE)
        self.log_btn, self.settings_btn = wx.Button(info_panel, label="Debug Log"), wx.Button(info_panel, label="Settings")
        act_row.Add(self.datasheet_btn, 1, wx.ALL, 2); act_row.Add(self.download_btn, 1, wx.ALL, 2); act_row.Add(self.log_btn, 1, wx.ALL, 2); act_row.Add(self.settings_btn, 1, wx.ALL, 2)
        info_sizer.Add(act_row, 0, wx.EXPAND); info_panel.SetSizer(info_sizer); right_panel_sizer.Add(info_panel, 0, wx.EXPAND | wx.ALL, 5)

        self.Bind(wx.EVT_CLOSE, self.on_close_dialog)
        self.search_btn.Bind(wx.EVT_BUTTON, self.on_new_search); self.search_ctrl.Bind(wx.EVT_TEXT_ENTER, self.on_new_search)
        self.stock_check.Bind(wx.EVT_CHECKBOX, self.on_filter_changed); self.basic_check.Bind(wx.EVT_CHECKBOX, self.on_filter_changed)
        self.list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_search_item_selected); self.list.Bind(wx.EVT_LIST_COL_CLICK, self.on_col_click)
        self.cart_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_cart_item_selected)
        self.remove_inst_btn.Bind(wx.EVT_BUTTON, self.on_delete_instance)
        self.add_to_cart_btn.Bind(wx.EVT_BUTTON, self.on_add_to_cart)
        self.qty_up_btn.Bind(wx.EVT_BUTTON, self.on_qty_up); self.qty_down_btn.Bind(wx.EVT_BUTTON, self.on_qty_down)
        self.remove_cart_btn.Bind(wx.EVT_BUTTON, self.on_remove_from_cart)
        self.prev_btn.Bind(wx.EVT_BUTTON, self.on_prev_page); self.next_btn.Bind(wx.EVT_BUTTON, self.on_next_page)
        self.image_ctrl.Bind(wx.EVT_LEFT_DOWN, self.on_image_zoom); self.symbol_preview.Bind(wx.EVT_LEFT_DOWN, self.on_symbol_zoom); self.footprint_preview.Bind(wx.EVT_LEFT_DOWN, self.on_footprint_zoom)
        self.datasheet_btn.Bind(wx.EVT_BUTTON, self.on_datasheet); self.download_btn.Bind(wx.EVT_BUTTON, self.on_download)
        self.log_btn.Bind(wx.EVT_BUTTON, self.on_show_log); self.settings_btn.Bind(wx.EVT_BUTTON, self.on_settings)
        
        # Global Library Bindings
        self.save_global_btn.Bind(wx.EVT_BUTTON, self.on_save_to_global)
        self.global_filter_ctrl.Bind(wx.EVT_TEXT, self.on_global_filter)
        self.global_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_global_item_selected)
        self.global_add_btn.Bind(wx.EVT_BUTTON, self.on_global_add_to_cart)
        self.global_remove_btn.Bind(wx.EVT_BUTTON, self.on_global_remove)

    def _update_global_list(self):
        self.global_list.DeleteAllItems()
        filter_text = self.global_filter_ctrl.GetValue().lower()
        self.global_metadata = self._load_global_metadata()
        for p in self.global_metadata:
            if filter_text and filter_text not in p["productModel"].lower() and filter_text not in p["productCode"].lower():
                continue
            idx = self.global_list.InsertItem(self.global_list.GetItemCount(), p["productModel"])
            self.global_list.SetItem(idx, 1, p["encapStandard"])
            self.global_list.SetItem(idx, 2, p["brand"])
            self.global_list.SetItem(idx, 3, p["productCode"])

    def on_global_filter(self, e): self._update_global_list()

    def on_global_item_selected(self, e):
        idx = e.GetIndex()
        # Find the actual metadata item (account for filtering)
        code = self.global_list.GetItemText(idx, 3)
        p = next((m for m in self.global_metadata if m["productCode"] == code), None)
        if p:
            self._show_preview(p)
            cart_p = next((item for item in self.cart_items if item["productCode"] == p["productCode"]), p)
            self._update_instance_list_ui(cart_p)

    def on_save_to_global(self, e):
        idx = self.list.GetFirstSelected()
        if idx == -1: return
        p = self.products[idx]
        threading.Thread(target=self._save_to_global_lib, args=(p,), daemon=True).start()

    def on_global_add_to_cart(self, e):
        idx = self.global_list.GetFirstSelected()
        if idx == -1: return
        code = self.global_list.GetItemText(idx, 3)
        p = next((m for m in self.global_metadata if m["productCode"] == code), None)
        if not p: return

        found = False
        target_idx = -1
        for i, item in enumerate(self.cart_items):
            if item["productCode"] == p["productCode"]:
                item["qty"] += 1; found = True; target_idx = i; break
        if not found:
            new_p = p.copy(); new_p["qty"] = 1; self.cart_items.append(new_p)
            target_idx = len(self.cart_items) - 1

        self._update_cart_list_ui(target_idx)
        self._save_project_components()
    def on_global_remove(self, e):
        idx = self.global_list.GetFirstSelected()
        if idx == -1: return
        code = self.global_list.GetItemText(idx, 3)
        
        metadata = self._load_global_metadata()
        metadata = [m for m in metadata if m["productCode"] != code]
        self._save_global_metadata(metadata)
        
        # Delete physical cache files
        g_cache = os.path.join(self._get_global_lib_dir(), "cache")
        for ext in ["json", "png"]:
            p = os.path.join(g_cache, f"{code}.{ext}")
            if os.path.exists(p): os.remove(p)
            
        self._update_global_list()

    def _log_to_console(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_buffer += f"[{ts}] {msg}\n"
        print(f"JLCPCB: {msg}")

    def _get_global_lib_dir(self):
        lib_dir = os.path.join(os.path.dirname(__file__), "global_lib")
        if not os.path.exists(lib_dir): os.makedirs(lib_dir, exist_ok=True)
        cache_dir = os.path.join(lib_dir, "cache")
        if not os.path.exists(cache_dir): os.makedirs(cache_dir, exist_ok=True)
        return lib_dir

    def _get_global_metadata_path(self):
        return os.path.join(self._get_global_lib_dir(), "metadata.json")

    def _load_global_metadata(self):
        path = self._get_global_metadata_path()
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f: return json.load(f)
            except: return []
        return []

    def _save_global_metadata(self, metadata):
        try:
            with open(self._get_global_metadata_path(), "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=4)
        except: pass

    def _save_to_global_lib(self, p):
        metadata = self._load_global_metadata()
        if any(m["productCode"] == p["productCode"] for m in metadata):
            wx.CallAfter(wx.MessageBox, "Component already in Global Library.", "Info", wx.ICON_INFORMATION)
            return
        
        # Save CAD and Photo to global cache
        g_cache = os.path.join(self._get_global_lib_dir(), "cache")
        
        # CAD
        cad = self._fetch_easyeda_models(p["productCode"])
        if cad:
            with open(os.path.join(g_cache, f"{p['productCode']}.json"), "w", encoding="utf-8") as f:
                json.dump(cad, f)
        
        # Photo
        if self.full_size_image_bytes:
            with open(os.path.join(g_cache, f"{p['productCode']}.png"), "wb") as f:
                f.write(self.full_size_image_bytes)
        
        metadata.append(p)
        self._save_global_metadata(metadata)
        wx.CallAfter(wx.MessageBox, f"Saved {p['productCode']} to Global Library.", "Success", wx.ICON_INFORMATION)
        wx.CallAfter(self._update_global_list)

    def _check_dependencies(self):
        def task():
            # Resolve correct python.exe path regardless of KiCad's sys.executable quirks
            import os, sys
            exe_dir = os.path.dirname(sys.executable)
            python_candidates = [
                os.path.join(exe_dir, "python.exe"),          # KiCad bin dir
                os.path.join(exe_dir, "python3.exe"),
                sys.executable,                                # fallback
            ]
            python_exe = next((p for p in python_candidates if os.path.isfile(p)), sys.executable)

            deps = [("easyeda2kicad", "easyeda2kicad")]
            for pkg, imp in deps:
                try:
                    __import__(imp)
                    self._log_to_console(f"Dependency '{pkg}' is already installed.")
                except ImportError:
                    self._log_to_console(f"Dependency '{pkg}' missing. Installing...")
                    try:
                        kwargs = {}
                        if sys.platform == "win32":
                            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
                        subprocess.check_call([python_exe, "-m", "pip", "install", pkg], **kwargs)
                        self._log_to_console(f"Successfully installed '{pkg}'.")
                    except Exception as e:
                        self._log_to_console(f"Failed to install '{pkg}': {e}")
        threading.Thread(target=task, daemon=True).start()

    def on_show_log(self, e): dlg = LogConsoleDialog(self); dlg.log_ctrl.SetValue(self.log_buffer); dlg.ShowModal(); dlg.Destroy()
    
    def on_close_dialog(self, event):
        self.settings["is_maximized"] = self.IsMaximized()
        if not self.IsMaximized(): self.settings["window_size"] = list(self.GetSize())
        self.settings["splitter_pos"] = self.main_splitter.GetSashPosition()
        self.settings["splitter_pos_v1"] = self.left_splitter_main.GetSashPosition()
        self.settings["splitter_pos_v2"] = self.left_splitter_bottom.GetSashPosition()
        save_settings(self.settings); event.Skip()

    def on_settings(self, event):
        dlg = SettingsDialog(self, self.settings)
        if dlg.ShowModal() == wx.ID_OK:
            self.settings = dlg.settings; save_settings(self.settings)
            self.symbol_preview.update_colors(self.settings["colors"]); self.footprint_preview.update_colors(self.settings["colors"])
        dlg.Destroy()

    def on_col_click(self, event):
        col = event.GetColumn()
        if col == self.sort_col: self.sort_desc = not self.sort_desc
        else: self.sort_col = col; self.sort_desc = False
        self.current_page = 1
        self.perform_search()

    def get_sort_mode(self):
        # self.sort_col: 0: Part, 1: Package, 2: Type, 3: Stock, 4: Price, 5: Brand, 6: LCSC #
        mapping = {
            0: "MODEL_SORT",
            1: "SPECIFICATION_SORT",
            3: "STOCK_SORT",
            4: "PRICE_SORT",
            5: "BRAND_SORT",
            6: "CODE_SORT"
        }
        return mapping.get(self.sort_col, "NORMAL")

    def on_new_search(self, e):
        self.current_keyword = self.search_ctrl.GetValue().strip()
        if not self.current_keyword: return
        self.current_page = 1; self.categories_map = {}; self.brands_map = {}
        self.sort_col = 0; self.sort_desc = False # Reset sort on new search
        self.perform_search()

    def on_filter_changed(self, e): self.current_page = 1; self.perform_search()

    def perform_search(self):
        if not self.current_keyword: return
        self.search_btn.Disable(); threading.Thread(target=self._search_thread, daemon=True).start()

    def _search_thread(self):
        try:
            if not self.xsrf_token:
                r = self.session.get(f"https://jlcpcb.com/api/overseas-pcb-order/v1/shoppingCart/smtGood/getXSRFToken", timeout=15, verify=False)
                self.xsrf_token = self.session.cookies.get("XSRF-TOKEN")
            
            payload = {
                "keyword": self.current_keyword, 
                "currentPage": self.current_page, 
                "pageSize": 50,
                "searchSource": "search",
                "searchType": 2,
                "presaleType": "stock",
                "sortMode": self.get_sort_mode(),
                "sortASC": "DESC" if self.sort_desc else "ASC"
            }
            if self.stock_check.GetValue(): payload["presaleTypes"] = ["stock"]
            if self.basic_check.GetValue(): payload["componentLibraryType"] = "base"

            headers = {
                'X-XSRF-TOKEN': self.xsrf_token, 
                'Content-Type': 'application/json',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Referer': 'https://jlcpcb.com/parts'
            }
            resp = self.session.post(f"https://jlcpcb.com/api/overseas-pcb-order/v1/shoppingCart/smtGood/selectSmtComponentList/v2", 
                                     json=payload, headers=headers, timeout=15, verify=False)
            data = resp.json().get('data') or {}

            items = (data.get('componentPageInfo') or {}).get('list') or []
            mapped = []
            for it in items:
                price_val = 0.0; plist = it.get('componentPrices') or []
                if plist: price_val = float(plist[0].get('productPrice', 0))

                # Intelligent Value detection for Passives
                raw_model = it.get("componentModelEn", "N/A")
                friendly_value = raw_model
                attrs = it.get("attributes") or []
                for a in attrs:
                    name = (a.get("attribute_name_en") or "").lower()
                    if name in ["resistance", "capacitance", "inductance", "nominal voltage"]:
                        friendly_value = a.get("attribute_value_name")
                        break

                mapped.append({
                    "productModel": raw_model,
                    "friendlyValue": friendly_value,
                    "productCode": it.get("componentCode", ""),
                    "encapStandard": it.get("componentSpecificationEn", "N/A"),
                    "type": "BASIC" if it.get("componentLibraryType") == "base" else "Extended",
                    "stockNumber": int(it.get("stockCount", 0)),
                    "price_val": price_val,
                    "brand": it.get("componentBrandEn", "N/A"),
                    "category": it.get("firstSortName", ""),
                    "attributes": attrs,
                    "pdfUrl": it.get("dataManualUrl", ""),
                    "photoId": it.get("productBigImageAccessId")
                })

            self.products = mapped; self.total_pages = ceil((data.get('componentPageInfo', {}).get('total') or 0) / 50)
            wx.CallAfter(self.update_list)
        except Exception as e: self._log_to_console(f"Search failed: {e}")
        finally: wx.CallAfter(self.search_btn.Enable)

    def update_list(self):
        self.list.DeleteAllItems()
        for p in self.products:
            idx = self.list.InsertItem(self.list.GetItemCount(), str(p["productModel"]))
            self.list.SetItem(idx, 1, str(p["encapStandard"]))
            self.list.SetItem(idx, 2, str(p["type"])); self.list.SetItem(idx, 3, str(p["stockNumber"]))
            self.list.SetItem(idx, 4, f"{p['price_val']}$"); self.list.SetItem(idx, 5, str(p["brand"]))
            self.list.SetItem(idx, 6, str(p["productCode"]))
        self.page_info.SetLabel(f"Page {self.current_page} / {self.total_pages}")

    def on_search_item_selected(self, event): 
        idx = event.GetIndex(); p = self.products[idx]; self._show_preview(p)
        cart_p = next((item for item in self.cart_items if item["productCode"] == p["productCode"]), p)
        self._update_instance_list_ui(cart_p)
    def on_cart_item_selected(self, event):
        idx = event.GetIndex()
        p = self.cart_items[idx]
        self._show_preview(p)
        self._update_instance_list_ui(p)

    def _update_instance_list_ui(self, p):
        self.instance_list.DeleteAllItems()
        project_path = os.path.dirname(pcbnew.GetBoard().GetFileName())
        for u_id in p.get("placed_uuids", []):
            ref = self.injector.get_instance_info_by_uuid(project_path, u_id)
            if ref:
                row = self.instance_list.InsertItem(self.instance_list.GetItemCount(), ref)
                self.instance_list.SetItem(row, 1, u_id)

    def on_delete_instance(self, e):
        # 1. Get selected instance
        inst_idx = self.instance_list.GetFirstSelected()
        if inst_idx == -1: return

        u_id = self.instance_list.GetItemText(inst_idx, 1)

        # 2. Find the component in the project that owns this UUID
        parent_p = None
        for item in self.cart_items:
            if u_id in item.get("placed_uuids", []):
                parent_p = item
                break

        if not parent_p:
            self._log_to_console(f"Error: Could not find parent component for instance {u_id}")
            return

        project_path = os.path.dirname(pcbnew.GetBoard().GetFileName())

        # 3. Physically remove from KiCad
        if self.injector.remove_instance_by_uuid(project_path, u_id):
            # 4. Update memory and JSON
            if u_id in parent_p["placed_uuids"]:
                parent_p["placed_uuids"].remove(u_id)
                parent_p["qty"] = len(parent_p["placed_uuids"])

            # 5. Refresh UI
            try:
                p_idx = self.cart_items.index(parent_p)
                self._update_cart_list_ui(p_idx)
            except:
                self._update_cart_list_ui()
            
            # Refresh instances for the parent (keeps the view consistent)
            self._update_instance_list_ui(parent_p)
            self._save_project_components()

            self._log_to_console(f"Instance {u_id} deleted successfully.")
    def _show_preview(self, p):
        try:
            self._log_to_console(f"--- Selection: {p['productCode']} ---")
            self.selected_product = p
            
            # Limpieza segura
            self.image_ctrl.clear(); self.full_size_image_bytes = None
            self.symbol_preview.load_data({}); self.footprint_preview.load_data({})
            self.cad_status_text.SetLabel("CAD Status: Loading...")
            
            self.title_text.SetLabel(f"{p['productModel']} ({p['productCode']})")
            self.prop_list.DeleteAllItems()
            for n, v in [("Manufacturer", p["brand"]), ("Category", p["category"]), ("Package", p["encapStandard"]), ("JLCPCB Code", p["productCode"])]:
                row = self.prop_list.GetItemCount(); self.prop_list.InsertItem(row, n); self.prop_list.SetItem(row, 1, str(v))

            for a in (p.get("attributes") or []):
                try:
                    row = self.prop_list.GetItemCount()
                    name = a.get("attribute_name_en") or a.get("attribute_name") or "Prop"
                    val = a.get("attribute_value_name") or "N/A"
                    self.prop_list.InsertItem(row, str(name))
                    self.prop_list.SetItem(row, 1, str(val))
                except: pass

            self.symbol_preview.loading = self.footprint_preview.loading = True; self.symbol_preview.Refresh(); self.footprint_preview.Refresh()
            
            p_code = p.get("productCode")
            if p_code:
                self._log_to_console(f"  Fetching CAD for {p_code}")
                threading.Thread(target=self._fetch_cad_thread, args=(p_code,), daemon=True).start()
                threading.Thread(target=self._load_photo_thread, args=(p_code, p.get("photoId")), daemon=True).start()
            else: self._log_to_console("  Error: Missing productCode")

        except Exception as e:
            self._log_to_console(f"Selection ERROR: {e}")
            self._log_to_console(traceback.format_exc())

    def _get_project_components_file(self):
        try:
            board = pcbnew.GetBoard()
            if not board: return None
            project_path = os.path.dirname(board.GetFileName())
            if not project_path: return None
            return os.path.join(project_path, "jlc_components.json")
        except: return None

    def _sync_components_from_schematic(self):
        try:
            board = pcbnew.GetBoard()
            if not board: return
            project_path = os.path.dirname(board.GetFileName())
            if not project_path: return

            symbols_found = self.injector.get_all_placed_jlc_symbols(project_path)
            if not symbols_found: return

            modified = False
            for s in symbols_found:
                pcode = s["pcode"]
                u_id = s["uuid"]
                
                already_in_cart = any(u_id in item.get("placed_uuids", []) for item in self.cart_items)
                if not already_in_cart:
                    cart_p = next((item for item in self.cart_items if item["productCode"] == pcode), None)
                    if cart_p:
                        if "placed_uuids" not in cart_p: cart_p["placed_uuids"] = []
                        if u_id not in cart_p["placed_uuids"]:
                            cart_p["placed_uuids"].append(u_id)
                            cart_p["qty"] = max(cart_p.get("qty", 1), len(cart_p["placed_uuids"]))
                            modified = True
                    else:
                        encap = s["fp"].split(":")[-1] if ":" in s["fp"] else s["fp"]
                        new_p = {
                            "productModel": s["val"] or pcode,
                            "friendlyValue": s["val"] or pcode,
                            "productCode": pcode,
                            "encapStandard": encap or "SMD",
                            "type": "Extended",
                            "stockNumber": 0,
                            "price_val": 0.0,
                            "brand": s["mfr"],
                            "category": "Schematic Recovered",
                            "attributes": [],
                            "pdfUrl": "",
                            "photoId": None,
                            "qty": 1,
                            "placed_uuids": [u_id]
                        }
                        self.cart_items.append(new_p)
                        modified = True

            if modified:
                self._save_project_components()
                self._log_to_console("Auto-synced and recovered components from schematic.")
        except Exception as e:
            self._log_to_console(f"Sync from schematic error: {e}")


    def _load_project_components(self):
        path = self._get_project_components_file()
        if path and os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    self.cart_items = json.load(f)
                self._log_to_console(f"Loaded {len(self.cart_items)} components from project file.")
            except Exception as e:
                self._log_to_console(f"Load error: {e}")

        self._sync_components_from_schematic()
        self._update_cart_list_ui()

    def _save_project_components(self):
        path = self._get_project_components_file()
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(self.cart_items, f, indent=4)
                # self._log_to_console("Project components saved.")
            except Exception as e:
                self._log_to_console(f"Save error: {e}")


    def _update_cart_list_ui(self, selected_idx=-1):
        self.cart_list.DeleteAllItems()
        for i, p in enumerate(self.cart_items):
            row = self.cart_list.InsertItem(self.cart_list.GetItemCount(), p["productModel"])
            self.cart_list.SetItem(row, 1, str(p.get("qty", 1)))
            self.cart_list.SetItem(row, 2, p["productCode"])
            self.cart_list.SetItem(row, 3, p["encapStandard"])
            if i == selected_idx:
                self.cart_list.Select(row)
                self.cart_list.Focus(row)

    def on_add_to_cart(self, e):
        idx = self.list.GetFirstSelected()
        last_idx = -1
        while idx != -1:
            p = self.products[idx].copy(); found = False
            for i, item in enumerate(self.cart_items):
                if item["productCode"] == p["productCode"]:
                    item["qty"] += 1; found = True; last_idx = i; break
            if not found:
                p["qty"] = 1; self.cart_items.append(p)
                last_idx = len(self.cart_items) - 1
            idx = self.list.GetNextSelected(idx)
        self._update_cart_list_ui(last_idx)
        self._save_project_components()

    def on_qty_up(self, e):
        idx = self.cart_list.GetFirstSelected()
        if idx != -1:
            self.cart_items[idx]["qty"] += 1
            self._update_cart_list_ui(idx)
            self._save_project_components()

    def on_qty_down(self, e):
        idx = self.cart_list.GetFirstSelected()
        if idx != -1:
            p = self.cart_items[idx]
            p["qty"] -= 1
            if p["qty"] <= 0:
                # Same logic as on_remove_from_cart for complete removal
                project_path = os.path.dirname(pcbnew.GetBoard().GetFileName())
                for u_id in p.get("placed_uuids", []):
                    self.injector.remove_instance_by_uuid(project_path, u_id)
                self._delete_from_cache(p["productCode"])
                self.cart_items.pop(idx)
                self.instance_list.DeleteAllItems()
                self._update_cart_list_ui() # Selection cleared as item is gone
            else:
                self._update_cart_list_ui(idx)
            self._save_project_components()

    def _delete_from_cache(self, code):
        for ext in ["png", "json"]:
            path = self._get_cache_path(code, ext)
            if path and os.path.exists(path):
                try: os.remove(path)
                except: pass

    def on_remove_from_cart(self, e):
        indices = []
        idx = self.cart_list.GetFirstSelected()
        while idx != -1:
            indices.append(idx)
            idx = self.cart_list.GetNextSelected(idx)
        
        if not indices: return
        
        project_path = os.path.dirname(pcbnew.GetBoard().GetFileName())
        # Remove in reverse to keep indices valid
        for i in sorted(indices, reverse=True):
            p = self.cart_items[i]
            # Physically remove all associated instances from schematic
            for u_id in p.get("placed_uuids", []):
                self.injector.remove_instance_by_uuid(project_path, u_id)
            
            # Clean up cache files
            self._delete_from_cache(p["productCode"])
            self.cart_items.pop(i)
            
        self._update_cart_list_ui()
        self.instance_list.DeleteAllItems() # Clear instance list as parent is gone
        self._save_project_components()


    def _get_cache_dir(self):
        try:
            board = pcbnew.GetBoard()
            if not board: return None
            project_path = os.path.dirname(board.GetFileName())
            if not project_path: return None
            lib_name = self.lib_folder_ctrl.GetValue().strip() or "EasyEDA_Components"
            cache_dir = os.path.join(project_path, lib_name, "cache")
            if not os.path.exists(cache_dir): os.makedirs(cache_dir, exist_ok=True)
            return cache_dir
        except: return None

    def _get_cache_path(self, code, ext):
        cdir = self._get_cache_dir()
        if not cdir: return None
        return os.path.join(cdir, f"{code}.{ext}")

    def _is_in_cart(self, code):
        return any(item["productCode"] == code for item in self.cart_items)

    def _load_photo_thread(self, code, photo_id):
        try:
            self._log_to_console(f"  Photo Thread: Fetching for {code}...")
            
            # 0. Check Project Cache First
            cache_file = self._get_cache_path(code, "png")
            if cache_file and os.path.exists(cache_file):
                with open(cache_file, "rb") as f:
                    data = f.read()
                    if data:
                        self._log_to_console(f"    Loaded photo from project cache: {code}.png")
                        self.full_size_image_bytes = data; wx.CallAfter(self._update_image_ui, data); return

            # 0b. Check Global Library Cache
            global_cache = os.path.join(self._get_global_lib_dir(), "cache", f"{code}.png")
            if os.path.exists(global_cache):
                with open(global_cache, "rb") as f:
                    data = f.read()
                    if data:
                        self._log_to_console(f"    Loaded photo from global library: {code}.png")
                        self.full_size_image_bytes = data; wx.CallAfter(self._update_image_ui, data); return

            # 1. Intentar JLC nativo
            if photo_id:
                url = f"https://jlcpcb.com/api/file/downloadByFileSystemAccessId/{photo_id}"
                self._log_to_console(f"    Trying JLC ID: {photo_id}")
                r = self.session.get(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://jlcpcb.com/"}, timeout=10, verify=False)
                self._log_to_console(f"    JLC Resp: {r.status_code} | Len: {len(r.content)}")
                if r.status_code == 200 and b"<html>" not in r.content[:500]:
                    self.full_size_image_bytes = r.content; wx.CallAfter(self._update_image_ui, r.content)
                    if cache_file and self._is_in_cart(code):
                        with open(cache_file, "wb") as f: f.write(r.content)
                    return
                else: self._log_to_console("    JLC ID failed or returned HTML.")

            # 2. Fallback a LCSC Detail
            url_lcsc = f"https://wmsc.lcsc.com/ftps/wm/product/detail?productCode={code}"
            self._log_to_console(f"    Trying LCSC Fallback: {url_lcsc}")
            r = requests.get(url_lcsc, headers={"User-Agent": "Mozilla/5.0"}, timeout=10, verify=False)
            detail = r.json().get("result") or {}
            imgs = detail.get("productImages") or []
            if imgs:
                img_url = imgs[0] if imgs[0].startswith('http') else 'https:' + imgs[0]
                self._log_to_console(f"    Downloading from LCSC: {img_url}")
                # IMPORTANTE: Referer para assets.lcsc.com
                headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.lcsc.com/"}
                r_img = requests.get(img_url, headers=headers, timeout=10, verify=False)
                self._log_to_console(f"    LCSC Resp: {r_img.status_code} | Len: {len(r_img.content)}")
                if r_img.status_code == 200:
                    self.full_size_image_bytes = r_img.content; wx.CallAfter(self._update_image_ui, r_img.content)
                    if cache_file and self._is_in_cart(code):
                        with open(cache_file, "wb") as f: f.write(r_img.content)
                else: self._log_to_console(f"    LCSC Download failed: {r_img.status_code}")
            else:
                self._log_to_console("    No images found in LCSC detail.")
        except Exception as e:
            self._log_to_console(f"  Photo Thread ERROR: {e}")
            import traceback
            self._log_to_console(traceback.format_exc())

    def _update_image_ui(self, data):
        self.image_ctrl.set_image_data(data)

    def _fetch_cad_thread(self, code):
        try:
            self._log_to_console(f"  CAD Thread started: {code}")
            cad = self._fetch_easyeda_models(code)
            if not cad: self._log_to_console("  CAD models not found in any server.")
            wx.CallAfter(self._update_cad_ui, cad)
        except Exception as e:
            self._log_to_console(f"  CAD Thread ERROR: {e}")
            self._log_to_console(traceback.format_exc())
            wx.CallAfter(self.cad_status_text.SetLabel, "CAD Status: Failed")

    def _fetch_easyeda_models(self, code):
        # 0. Check Project Cache First
        cache_file = self._get_cache_path(code, "json")
        if cache_file and os.path.exists(cache_file):
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    self._log_to_console(f"    Loaded CAD from project cache: {code}.json")
                    return json.load(f)
            except: pass

        # 0b. Check Global Library Cache
        global_cache = os.path.join(self._get_global_lib_dir(), "cache", f"{code}.json")
        if os.path.exists(global_cache):
            try:
                with open(global_cache, "r", encoding="utf-8") as f:
                    self._log_to_console(f"    Loaded CAD from global library: {code}.json")
                    return json.load(f)
            except: pass

        for url in [f"https://lceda.cn/api/products/{code}/components", f"https://easyeda.com/api/products/{code}/components"]:
            try:
                self._log_to_console(f"    Requesting: {url}")
                r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=8, verify=False)
                if r.status_code == 200:
                    data = r.json()
                    if data.get("success") and data.get("result"):
                        self._log_to_console(f"    CAD data found on {url}")
                        res = data["result"]
                        if isinstance(res.get("dataStr"), str):
                            try: res["dataStr"] = json.loads(res["dataStr"])
                            except: pass
                        if res.get("packageDetail") and isinstance(res["packageDetail"].get("dataStr"), str):
                            try: res["packageDetail"]["dataStr"] = json.loads(res["packageDetail"]["dataStr"])
                            except: pass
                        
                        # Save to Cache ONLY if item is in the project
                        if cache_file and self._is_in_cart(code):
                            with open(cache_file, "w", encoding="utf-8") as f: json.dump(res, f)
                        
                        return res
            except Exception as e:
                self._log_to_console(f"    Error on {url}: {e}")
                continue
        return None

    def _update_cad_ui(self, cad):
        try:
            self.cad_data = cad; has_s = has_f = has_3d = False
            self.symbol_preview.loading = self.footprint_preview.loading = False
            if cad:
                self._log_to_console("  Updating UI Panels...")
                sym = cad.get("dataStr")
                if sym: self.symbol_preview.load_data(sym); has_s = True
                pkg = cad.get("packageDetail", {}).get("dataStr")
                if pkg:
                    self.footprint_preview.load_data(pkg); has_f = True
                    if "3DModel" in str(pkg): has_3d = True
            self.cad_status_text.SetLabel(f"CAD: {'✅' if has_s else '❌'} Sym, {'✅' if has_f else '❌'} Foot, {'✅' if has_3d else '❌'} 3D")
            self.download_btn.Enable(has_s or has_f); self.symbol_preview.Refresh(); self.footprint_preview.Refresh()
            self._log_to_console("  UI Panels updated.")
        except Exception as e:
            self._log_to_console(f"  UI Update ERROR: {e}")
            self._log_to_console(traceback.format_exc())

    def on_prev_page(self, e): 
        if self.current_page > 1: self.current_page -= 1; self.perform_search()
    def on_next_page(self, e):
        if self.current_page < self.total_pages: self.current_page += 1; self.perform_search()
    def on_image_zoom(self, e):
        if self.full_size_image_bytes: ImagePopupDialog(self, self.full_size_image_bytes, "Photo Zoom").ShowModal()
    def on_symbol_zoom(self, e):
        if self.cad_data and self.cad_data.get("dataStr"): RendererPopupDialog(self, self.cad_data.get("dataStr"), 'symbol', "Symbol Zoom", self.settings["colors"]).ShowModal()
    def on_footprint_zoom(self, e):
        fp = self.cad_data.get("packageDetail", {}).get("dataStr") if self.cad_data else None
        if fp: RendererPopupDialog(self, fp, 'footprint', "Footprint Zoom", self.settings["colors"]).ShowModal()
    def on_datasheet(self, e):
        if self.selected_product and self.selected_product.get("pdfUrl"): webbrowser.open(self.selected_product["pdfUrl"])
    def on_download(self, e):
        if not self.cart_items: return
        lib_name = self.lib_folder_ctrl.GetValue().strip() or "EasyEDA_Components"
        threading.Thread(target=self._download_task, args=(lib_name,), daemon=True).start()

    def _download_task(self, lib_name):
        try:
            import easyeda2kicad.__main__ as e2k_main
            from easyeda2kicad.easyeda.easyeda_api import EasyedaApi
            original_get_info = EasyedaApi.get_info_from_easyeda_api
            
            board = pcbnew.GetBoard(); project_path = os.path.dirname(board.GetFileName())
            if not project_path: wx.CallAfter(wx.MessageBox, "Save project first.", "Error", wx.ICON_ERROR); return
            
            lib_path = os.path.join(project_path, lib_name); os.makedirs(lib_path, exist_ok=True)
            master_sym_file = os.path.join(lib_path, f"{lib_name}.kicad_sym")
            master_fp_dir = os.path.join(lib_path, f"{lib_name}.pretty"); os.makedirs(master_fp_dir, exist_ok=True)
            
            if not os.path.exists(master_sym_file):
                with open(master_sym_file, "w", encoding="utf-8") as f:
                    f.write('(kicad_symbol_lib (version 20211014) (generator "KiCad_JLCPCB_Search")\n)\n')

            success_count = 0
            
            for i, p in enumerate(self.cart_items):
                pcode = p["productCode"]
                qty = p.get("qty", 1)
                
                # 1. Sync UUIDs with schematic
                placed_uuids = p.get("placed_uuids", [])
                p["placed_uuids"] = [u for u in placed_uuids if self.injector.get_instance_info_by_uuid(project_path, u) is not None]
                
                # 2. Check if we need to add more instances or if footprint file is missing
                needed = max(0, qty - len(p["placed_uuids"]))
                fp_file = os.path.join(master_fp_dir, f"{pcode}.kicad_mod")
                fp_missing = not os.path.exists(fp_file)

                lib_exists = False
                try:
                    with open(master_sym_file, "r", encoding="utf-8") as f:
                        if f'(symbol "{pcode}"' in f.read(): lib_exists = True
                except: pass

                if needed <= 0 and not fp_missing and lib_exists:
                    self._log_to_console(f"Skipping {pcode}: Library and all instances up to date.")
                    continue

                wx.CallAfter(self.cad_status_text.SetLabel, f"Processing {i+1}/{len(self.cart_items)}: {pcode}")
                
                # 3. Check if library work is needed (symbol or footprint file missing)
                sym_block = None
                if not lib_exists or fp_missing:
                    # Download CAD and consolidate footprint/symbol
                    cad = self._fetch_easyeda_models(pcode)
                    if cad:
                        norm_cad = cad.copy()
                        if isinstance(norm_cad.get("dataStr"), str): norm_cad["dataStr"] = json.loads(norm_cad["dataStr"])
                        if norm_cad.get("packageDetail") and isinstance(norm_cad["packageDetail"].get("dataStr"), str):
                            norm_cad["packageDetail"]["dataStr"] = json.loads(norm_cad["packageDetail"]["dataStr"])
                        
                        EasyEDASearchDialog.cached_cad_data = norm_cad
                        EasyedaApi.get_info_from_easyeda_api = lambda *args, **kwargs: {"result": EasyEDASearchDialog.cached_cad_data}
                        
                        temp_prefix = os.path.join(lib_path, f"_tmp_{pcode}")
                        try: e2k_main.main(["--full", "--lcsc_id", pcode, "--output", temp_prefix, "--overwrite"])
                        except: pass
                        
                        sym_block = self.injector.extract_and_fix_symbol_to_master(lib_path, pcode, lib_name)
                        self.injector.consolidate_footprint_to_master(lib_path, pcode, master_fp_dir, lib_name)
                        
                        # Cleanup
                        for f in os.listdir(lib_path):
                            if f.startswith(f"_tmp_{pcode}"):
                                path = os.path.join(lib_path, f)
                                if os.path.isdir(path): shutil.rmtree(path)
                                else: os.remove(path)
                else:
                    sym_block = self._get_symbol_block_from_master(master_sym_file, pcode)

                # 4. Inject instances into schematic only if needed > 0
                if needed > 0:
                    if sym_block:
                        self.injector.inject_symbol_to_cache(project_path, pcode, sym_block, lib_name)
                        
                    prefix = self.injector.get_prefix(p)
                    for _ in range(needed):
                        u_id = self.injector.inject_instance_to_schematic(
                            project_path, pcode, p.get("friendlyValue", ""), lib_name, prefix,
                            manufacturer=p.get("brand", "N/A")
                        )
                        if u_id: p["placed_uuids"].append(u_id)
                
                success_count += 1

            
            # Save the updated list (with UUIDs)
            self._save_project_components()
            self._register_project_libraries(project_path, lib_name)
            
            def ui_refresh():
                old_idx = self.cart_list.GetFirstSelected()
                self._update_cart_list_ui(old_idx)
                idx = self.cart_list.GetFirstSelected()
                if idx != -1: self._update_instance_list_ui(self.cart_items[idx])
                else:
                    search_idx = self.list.GetFirstSelected()
                    if search_idx != -1:
                        p = self.products[search_idx]
                        cart_p = next((item for item in self.cart_items if item["productCode"] == p["productCode"]), p)
                        self._update_instance_list_ui(cart_p)
            wx.CallAfter(ui_refresh)
            EasyedaApi.get_info_from_easyeda_api = original_get_info
            
            wx.CallAfter(wx.MessageBox, f"Success! Consolidated {success_count} parts into '{lib_name}'.\n\nOld individual libraries have been removed from the tables.", "Complete", wx.ICON_INFORMATION)
        except Exception as e:
            self._log_to_console(traceback.format_exc())
            wx.CallAfter(wx.MessageBox, f"Error: {e}", "Error", wx.ICON_ERROR)

    def _get_symbol_block_from_master(self, master_file, pcode):
        try:
            if not os.path.exists(master_file): return None
            with open(master_file, "r", encoding="utf-8") as f:
                content = f.read()
                start = content.find(f'(symbol "{pcode}"')
                if start == -1: return None
                p_count = 0; block = ""
                for i in range(start, len(content)):
                    char = content[i]; block += char
                    if char == '(': p_count += 1
                    elif char == ')':
                        p_count -= 1
                        if p_count == 0: break
                return block
        except: return None

    def _register_project_libraries(self, project_path, lib_name):
        def clean_and_update_table(table_path, name, rel_uri, type_str):
            header = "sym_lib_table" if type_str == "sym" else "fp_lib_table"
            new_entry = f'  (lib (name "{name}")(type "KiCad")(uri "{rel_uri}")(options "")(descr "EasyEDA Consolidated {type_str}"))\n'
            
            content = f"({header}\n{new_entry})\n"
            if os.path.exists(table_path):
                with open(table_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                
                # Filtrar de forma SEGURA:
                # Solo borramos si el nombre es C+números Y la ruta contiene nuestra carpeta de componentes
                filtered_lines = []
                for line in lines:
                    if header in line or line.strip() == ")": continue
                    
                    is_old_jlc = re.search(r'\(name "C\d+"\)', line)
                    is_in_plugin_folder = f"/{lib_name}/" in line or f"\\{lib_name}\\" in line
                    
                    # Si es un componente LCSC dentro de nuestra carpeta, lo borramos (limpieza)
                    if is_old_jlc and is_in_plugin_folder: continue
                    
                    # Borrar la entrada de la propia librería maestra si ya existía (para actualizarla)
                    if f'(name "{name}")' in line: continue
                    
                    filtered_lines.append(line)
                
                content = f"({header}\n" + "".join(filtered_lines) + new_entry + ")\n"
            
            with open(table_path, "w", encoding="utf-8") as f:
                f.write(content)
        
        sym_rel = f"${{KIPRJMOD}}/{lib_name}/{lib_name}.kicad_sym"
        fp_rel = f"${{KIPRJMOD}}/{lib_name}/{lib_name}.pretty"
        
        clean_and_update_table(os.path.join(project_path, "fp-lib-table"), lib_name, fp_rel, "fp")
        clean_and_update_table(os.path.join(project_path, "sym-lib-table"), lib_name, sym_rel, "sym")

