import os
import pcbnew

class PcbInjector:
    def __init__(self, log_callback=None):
        self.log_callback = log_callback

    def _log(self, msg):
        if self.log_callback:
            self.log_callback(f"[PCBInjector] {msg}")
        else:
            print(f"[PCBInjector] {msg}")

    def is_footprint_on_board(self, board, u_id):
        if not board:
            return False
        try:
            target_path = f"/{u_id}"
            for fp in board.GetFootprints():
                if fp.GetPath().AsString() == target_path:
                    return True
            return False
        except Exception as e:
            self._log(f"is_footprint_on_board error: {e}")
            return False

    def inject_footprint_to_board(self, board, pcode, master_fp_dir, ref_designator, model_name, u_id, manufacturer="N/A", sch_path=None):
        if not board or not master_fp_dir:
            return False
        try:
            if self.is_footprint_on_board(board, u_id):
                self._log(f"Footprint {ref_designator} ({u_id}) already exists on PCB board.")
                return True

            fp = pcbnew.FootprintLoad(master_fp_dir, pcode)
            if not fp:
                self._log(f"Could not load footprint from {master_fp_dir} for {pcode}")
                return False

            fp.SetReference(ref_designator)
            fp.SetValue(model_name)

            # Match UUID path with schematic symbol
            try:
                fp.SetPath(pcbnew.KIID_PATH(f"/{u_id}"))
                fp.SetSheetname("/")
                if sch_path:
                    fp.SetSheetfile(os.path.basename(sch_path))
            except Exception as e:
                self._log(f"SetPath error: {e}")

            # SMT / LCSC attributes
            try:
                fp.SetProperty("JLCPCB Part #", pcode)
                fp.SetProperty("LCSC Part #", pcode)
                if manufacturer and manufacturer != "N/A":
                    fp.SetProperty("Manufacturer", manufacturer)
            except Exception:
                pass

            # Smart placement on PCB (avoid overlapping)
            try:
                existing_fps = board.GetFootprints()
                idx = len(existing_fps)
                x_mm = 50 + (idx % 8) * 20
                y_mm = 50 + (idx // 8) * 20
                fp.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(x_mm), pcbnew.FromMM(y_mm)))
            except Exception:
                pass

            board.Add(fp)
            self._log(f"Injected footprint {ref_designator} directly to PCB board.")
            return True
        except Exception as e:
            self._log(f"Inject footprint to board error: {e}")
            return False

    def remove_footprint_from_board(self, board, u_id):
        if not board:
            return False
        try:
            target_path = f"/{u_id}"
            for fp in board.GetFootprints():
                if fp.GetPath().AsString() == target_path:
                    ref = fp.GetReference()
                    board.Remove(fp)
                    self._log(f"Removed footprint {ref} ({u_id}) from PCB board.")
                    return True
            return False
        except Exception as e:
            self._log(f"Remove footprint from board error: {e}")
            return False
