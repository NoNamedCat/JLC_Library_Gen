
import wx
import math
import re

class EasyEDARendererBase(wx.Panel):
    def __init__(self, parent):
        super().__init__(parent, style=wx.FULL_REPAINT_ON_RESIZE)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.data = None
        self.loading = False
        self.scale = 1.0
        self.center_offset = [0, 0]
        self.comp_width = 100
        self.comp_height = 100
        # Colores por defecto (se sobrescribiran por la config del plugin)
        self.colors = {
            'Background': wx.Colour(20, 20, 20),
            'SymbolBody': wx.Colour(200, 50, 50),
            'Pin': wx.Colour(200, 200, 200),
            'PinName': wx.Colour(50, 220, 220),
            'PinNum': wx.Colour(220, 220, 50),
            'Copper': wx.Colour(200, 80, 80),
            'Silk': wx.Colour(255, 255, 100),
            'Fab': wx.Colour(150, 150, 150),
            'Pad': wx.Colour(200, 200, 150),
            'PadText': wx.Colour(30, 30, 30)
        }
        self.Bind(wx.EVT_PAINT, self.on_paint)
        self.Bind(wx.EVT_SIZE, self.on_size)

    def update_colors(self, new_colors):
        """Actualiza los colores y refresca el panel."""
        for k, v in new_colors.items():
            if k in self.colors:
                self.colors[k] = wx.Colour(v) if isinstance(v, str) else v
        self.Refresh()

    def world_to_screen(self, x, y, w, h):
        return (float(x) - self.center_offset[0]) * self.scale + w / 2, (float(y) - self.center_offset[1]) * self.scale + h / 2

    def on_size(self, event):
        self.auto_fit()
        self.Refresh()
        event.Skip()

    def parse_path(self, path_str, w, h):
        path_str = path_str.split('~')[0]
        tokens = re.findall(r'([A-Za-z])|([-+]?\d*\.\d+|[-+]?\d+)', path_str)
        path = wx.GraphicsContext.Create().CreatePath()
        curr_x, curr_y = 0.0, 0.0
        i = 0
        while i < len(tokens):
            cmd = tokens[i][0]
            if not cmd: i += 1; continue
            i += 1; params = []
            while i < len(tokens) and tokens[i][1]:
                params.append(float(tokens[i][1])); i += 1
            try:
                if cmd == 'M': curr_x, curr_y = params[0], params[1]; path.MoveToPoint(*self.world_to_screen(curr_x, curr_y, w, h))
                elif cmd == 'm': curr_x += params[0]; curr_y += params[1]; path.MoveToPoint(*self.world_to_screen(curr_x, curr_y, w, h))
                elif cmd == 'L': curr_x, curr_y = params[0], params[1]; path.AddLineToPoint(*self.world_to_screen(curr_x, curr_y, w, h))
                elif cmd == 'l': curr_x += params[0]; curr_y += params[1]; path.AddLineToPoint(*self.world_to_screen(curr_x, curr_y, w, h))
                elif cmd == 'H': curr_x = params[0]; path.AddLineToPoint(*self.world_to_screen(curr_x, curr_y, w, h))
                elif cmd == 'h': curr_x += params[0]; path.AddLineToPoint(*self.world_to_screen(curr_x, curr_y, w, h))
                elif cmd == 'V': curr_y = params[0]; path.AddLineToPoint(*self.world_to_screen(curr_x, curr_y, w, h))
                elif cmd == 'v': curr_y += params[0]; path.AddLineToPoint(*self.world_to_screen(curr_x, curr_y, w, h))
                elif cmd in ['Z', 'z']: path.CloseSubpath()
            except: pass
        return path

    def auto_fit(self):
        if not self.data: return
        bbox = self.data.get('BBox')
        if bbox:
            self.min_x, self.min_y = float(bbox.get('x', 0)), float(bbox.get('y', 0))
            self.comp_width, self.comp_height = float(bbox.get('width', 100)), float(bbox.get('height', 100))
        else:
            pts = []
            for s in self.data.get('shape', []):
                p = s.split('~')
                if p[0] == 'P': pts.append((float(p[4]), float(p[5])))
                elif p[0] == 'PAD': pts.append((float(p[2]), float(p[3])))
            if not pts: return
            self.min_x, max_x = min(pts, key=lambda x:x[0])[0], max(pts, key=lambda x:x[0])[0]
            self.min_y, max_y = min(pts, key=lambda x:x[1])[1], max(pts, key=lambda x:x[1])[1]
            self.comp_width, self.comp_height = max(1, self.max_x-self.min_x), max(1, self.max_y-self.min_y)
        w, h = self.GetClientSize()
        if w < 10 or h < 10: return
        self.scale = min((w * 0.85) / self.comp_width, (h * 0.85) / self.comp_height)
        self.center_offset = [self.min_x + self.comp_width/2, self.min_y + self.comp_height/2]

class EasyEDASymbolPanel(EasyEDARendererBase):
    def load_data(self, data_obj):
        self.data = data_obj; self.auto_fit(); self.Refresh()

    def on_paint(self, event):
        dc = wx.AutoBufferedPaintDC(self); w, h = self.GetClientSize()
        dc.SetBackground(wx.Brush(self.colors['Background'])); dc.Clear()
        if not hasattr(self, '_last_size') or self._last_size != (w, h): self.auto_fit(); self._last_size = (w, h)
        if getattr(self, 'loading', False):
            dc.SetFont(wx.Font(12, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
            dc.SetTextForeground(wx.Colour(200, 200, 200)); txt = "Loading CAD Data..."
            tw, th = dc.GetTextExtent(txt); dc.DrawText(txt, int(w/2 - tw/2), int(h/2 - th/2)); return
        if not self.data: return
        gc = wx.GraphicsContext.Create(dc)
        if not gc: return

        text_queue = []
        for shape_str in self.data.get('shape', []):
            parts = shape_str.split('~'); stype = parts[0]
            try:
                if stype == 'R':
                    x, y = self.world_to_screen(parts[1], parts[2], w, h); sw, sh = float(parts[5])*self.scale, float(parts[6])*self.scale
                    gc.SetPen(wx.Pen(self.colors['SymbolBody'], 2)); gc.SetBrush(wx.Brush(wx.Colour(150, 50, 50, 40))); gc.DrawRectangle(x, y, sw, sh)
                elif stype == 'E':
                    x, y = self.world_to_screen(parts[1], parts[2], w, h); rx = float(parts[3])*self.scale
                    gc.SetPen(wx.Pen(self.colors['SymbolBody'], 2)); gc.DrawEllipse(x-rx, y-rx, rx*2, rx*2)
                elif stype == 'PL':
                    coords = parts[1].split(' '); path = gc.CreatePath(); path.MoveToPoint(*self.world_to_screen(coords[0], coords[1], w, h))
                    for i in range(2, len(coords), 2): path.AddLineToPoint(*self.world_to_screen(coords[i], coords[i+1], w, h))
                    gc.SetPen(wx.Pen(self.colors['SymbolBody'], 2)); gc.StrokePath(path)
                elif stype == 'P':
                    px, py = self.world_to_screen(parts[4], parts[5], w, h); sub = shape_str.split('^^')
                    gc.SetPen(wx.Pen(self.colors['Pin'], 2))
                    for sp in sub:
                        # PRIORIDAD: Si empieza por 1~ es texto, sin importar que contenga letras de path
                        if sp.startswith('1~'): text_queue.append(sp)
                        elif any(c in sp for c in 'MLHVmlhv'): gc.StrokePath(self.parse_path(sp, w, h))
                    gc.SetBrush(wx.Brush(self.colors['Pin'])); gc.DrawEllipse(px-2, py-2, 4, 4)
            except: continue

        # Fase 2: Textos (Encima)
        # Usar escala directa por unidad interna (reducida para mas limpieza)
        font_sz_name = max(4, int(6.5 * self.scale))
        font_sz_num = max(3, int(5.0 * self.scale))

        for t_str in text_queue:
            p = t_str.split('~'); tx, ty = self.world_to_screen(p[1], p[2], w, h); txt = p[4]; rot = float(p[3] if p[3] else 0); align = p[5] if len(p)>5 else 'start'
            is_num = not any(c.isalpha() for c in txt)
            
            gc.SetFont(wx.Font(font_sz_num if is_num else font_sz_name, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL), self.colors['PinNum'] if is_num else self.colors['PinName'])
            tw, th = gc.GetTextExtent(txt)

            if rot == 90 or rot == 270: # Pines Verticales
                final_rot = 90 # Leer de abajo a arriba
                # Ajuste de anclaje basado en el align real del JSON
                final_ox = 0
                if align == 'end': final_ox = -tw
                elif align == 'center': final_ox = -tw/2

                # Centrado axial reforzado hacia la izquierda (altura/2 + margen)
                # Subimos de 0.5 a 0.7 para terminar de corregir el desplazamiento a la derecha
                final_oy = -th * 0.7

                gc.PushState(); gc.Translate(tx, ty); gc.Rotate(-math.radians(final_rot))
                gc.DrawText(txt, final_ox, final_oy); gc.PopState()

            else:
                # Comportamiento estandar para pines laterales
                final_ox = 0
                if align == 'end': final_ox = -tw
                elif align == 'center': final_ox = -tw/2
                gc.PushState(); gc.Translate(tx, ty); gc.Rotate(-math.radians(rot))
                # Ajuste de Y: subimos el numero 0.4 adicionales respecto al -0.3 anterior (-th * 0.7)
                gc.DrawText(txt, final_ox, -th / 1.2 if not is_num else -th * 0.7); gc.PopState()

class EasyEDAFootprintPanel(EasyEDARendererBase):
    def load_data(self, data_obj):
        self.data = data_obj; self.auto_fit(); self.Refresh()

    def on_paint(self, event):
        dc = wx.AutoBufferedPaintDC(self); w, h = self.GetClientSize()
        dc.SetBackground(wx.Brush(self.colors['Background'])); dc.Clear()
        if not hasattr(self, '_last_size') or self._last_size != (w, h): self.auto_fit(); self._last_size = (w, h)
        
        if getattr(self, 'loading', False):
            dc.SetFont(wx.Font(12, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
            dc.SetTextForeground(wx.Colour(200, 200, 200)); txt = "Loading CAD Data..."
            tw, th = dc.GetTextExtent(txt); dc.DrawText(txt, int(w/2 - tw/2), int(h/2 - th/2)); return

        if not self.data: return
        gc = wx.GraphicsContext.Create(dc)
        if not gc: return

        for s in self.data.get('shape', []):
            p = s.split('~')
            if p[0] == 'SOLIDREGION' and p[1] == '1':
                path = self.parse_path(p[3], w, h); gc.SetBrush(wx.Brush(wx.Colour(self.colors['Copper'].Red(), self.colors['Copper'].Green(), self.colors['Copper'].Blue(), 150)))
                gc.SetPen(wx.Pen(self.colors['Copper'], 1)); gc.FillPath(path); gc.StrokePath(path)

        for s in self.data.get('shape', []):
            p = s.split('~')
            if p[0] == 'PAD':
                try:
                    px, py = self.world_to_screen(p[2], p[3], w, h); pw, ph = float(p[4])*self.scale, float(p[5])*self.scale
                    ang = float(p[11]) if len(p)>11 else 0.0; num = p[8]
                    gc.SetBrush(wx.Brush(self.colors['Pad'])); gc.SetPen(wx.Pen(wx.Colour(100, 100, 50), 1))
                    gc.PushState(); gc.Translate(px, py); gc.Rotate(math.radians(ang))
                    if p[1] == 'ELLIPSE': gc.DrawEllipse(-pw/2, -ph/2, pw, ph)
                    else: gc.DrawRectangle(-pw/2, -ph/2, pw, ph)
                    font_sz = max(4, int(min(pw, ph)*0.6)); gc.SetFont(wx.Font(font_sz, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD), self.colors['PadText'])
                    tw, th = gc.GetTextExtent(num); draw_ang = 0
                    if 90 < (ang % 360) <= 270: draw_ang = math.pi
                    gc.Rotate(draw_ang); gc.DrawText(num, -tw/2, -th/2); gc.PopState()
                except: continue

        for s in self.data.get('shape', []):
            p = s.split('~'); stype = p[0]
            try:
                if stype == 'TRACK':
                    layer = p[1]; width = float(p[2])*self.scale; coords = p[4].split(' ')
                    color = self.colors['Silk'] if layer == '3' else self.colors['Fab']
                    gc.SetPen(wx.Pen(color, max(1, int(width/10)))); path = gc.CreatePath(); path.MoveToPoint(*self.world_to_screen(coords[0], coords[1], w, h))
                    for i in range(2, len(coords), 2): path.AddLineToPoint(*self.world_to_screen(coords[i], coords[i+1], w, h))
                    gc.StrokePath(path)
                elif stype == 'SOLIDREGION' and p[1] not in ['1', '99']:
                    color = self.colors['Silk'] if p[1] == '3' else self.colors['Fab']
                    path = self.parse_path(p[3], w, h); gc.SetBrush(wx.Brush(wx.Colour(color.Red(), color.Green(), color.Blue(), 100)))
                    gc.SetPen(wx.Pen(color, 1)); gc.FillPath(path); gc.StrokePath(path)
                elif stype == 'CIRCLE':
                    x, y = self.world_to_screen(p[1], p[2], w, h); r = float(p[3])*self.scale
                    gc.SetPen(wx.Pen(self.colors['Silk'], 1)); gc.DrawEllipse(x-r, y-r, r*2, r*2)
                elif stype == 'RECT' and p[5] != '99':
                    x, y = self.world_to_screen(p[1], p[2], w, h); sw, sh = float(p[3])*self.scale, float(p[4])*self.scale
                    gc.PushState(); gc.Translate(x+sw/2, y+sh/2); gc.Rotate(math.radians(float(p[7]) if len(p)>7 else 0.0))
                    gc.SetPen(wx.Pen(self.colors['Silk'] if p[5]=='3' else self.colors['Fab'], 1)); gc.DrawRectangle(-sw/2, -sh/2, sw, sh); gc.PopState()
            except: continue
