import pcbnew
import os
import importlib

class EasyEDASearchPlugin(pcbnew.ActionPlugin):
    def defaults(self):
        self.name = "JLC Library Gen"
        self.category = "Search"
        self.description = "Advanced component search with JLC SMT support."
        self.show_toolbar_button = True
        self.icon_file_name = os.path.join(os.path.dirname(__file__), 'icon_32x32.png')

    def Run(self):
        import wx
        from . import schematic_injector
        from . import pcb_injector
        from . import easyeda_search
        importlib.reload(schematic_injector)
        importlib.reload(pcb_injector)
        importlib.reload(easyeda_search)
        parent = None
        try:
            top_windows = wx.GetTopLevelWindows()
            if top_windows:
                parent = top_windows[0]
        except Exception:
            parent = None
        dialog = easyeda_search.EasyEDASearchDialog(parent)
        dialog.ShowModal()
        dialog.Destroy()

EasyEDASearchPlugin().register()

