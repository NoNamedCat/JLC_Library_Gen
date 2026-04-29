import pcbnew
import os
from .easyeda_search import EasyEDASearchDialog

class EasyEDASearchPlugin(pcbnew.ActionPlugin):
    def defaults(self):
        self.name = "JLC Library Gen"
        self.category = "Search"
        self.description = "Advanced component search with JLC SMT support."
        self.show_toolbar_button = True
        self.icon_file_name = os.path.join(os.path.dirname(__file__), 'icon_32x32.png')

    def Run(self):
        dialog = EasyEDASearchDialog(None)
        dialog.ShowModal()
        dialog.Destroy()

EasyEDASearchPlugin().register()
