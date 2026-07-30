
import os
import re
import shutil
import uuid
import pcbnew
import json

class SchematicInjector:
    def __init__(self, log_callback=None):
        self.log_callback = log_callback

    def _log(self, msg):
        if self.log_callback:
            self.log_callback(msg)

    def get_prefix(self, item):
        cat = (item.get("category") or "").lower()
        model = (item.get("productModel") or "").lower()
        if "resistor" in cat or "resistor" in model: return "R"
        if "capacitor" in cat or "capacitor" in model: return "C"
        if "inductor" in cat or "bead" in cat or "bead" in model: return "L"
        if "diode" in cat or "led" in cat or "led" in model: return "D"
        if "transistor" in cat or "mosfet" in cat: return "Q"
        if "connector" in cat: return "J"
        if "crystal" in cat or "oscillator" in cat: return "Y"
        if "fuse" in cat: return "F"
        if "switch" in cat: return "SW"
        return "U"

    def get_sch_path(self, project_path):
        sch_files = [f for f in os.listdir(project_path) if f.endswith(".kicad_sch")]
        if not sch_files: return None
        board_name = os.path.basename(pcbnew.GetBoard().GetFileName()).replace(".kicad_pcb", "")
        if f"{board_name}.kicad_sch" in sch_files: return os.path.join(project_path, f"{board_name}.kicad_sch")
        return os.path.join(project_path, sch_files[0])

    def extract_and_fix_symbol_to_master(self, lib_path, pcode, lib_name):
        temp_sym = os.path.join(lib_path, f"_tmp_{pcode}.kicad_sym")
        if not os.path.exists(temp_sym): return None
        try:
            with open(temp_sym, "r", encoding="utf-8") as f:
                content = f.read()
                
                # 1. Identify original symbol name
                match = re.search(r'\(symbol "(.*?)"', content)
                if not match: return None
                original_name = match.group(1)
                
                # 2. Global replace of original_name with pcode
                content = content.replace(f'"{original_name}"', f'"{pcode}"')
                content = content.replace(f'"{original_name}_', f'"{pcode}_')
                
                # 3. Fix Footprint reference to use MasterLib:LCSC
                content = re.sub(r'\(property\s+"Footprint"\s+"[^"]*"', f'(property "Footprint" "{lib_name}:{pcode}"', content)
                
                # 4. Extract the main block
                start = content.find(f'(symbol "{pcode}"')
                if start == -1: return None
                p_count = 0; block = ""
                for i in range(start, len(content)):
                    char = content[i]; block += char
                    if char == '(': p_count += 1
                    elif char == ')':
                        p_count -= 1
                        if p_count == 0: break
                
                # 5. Append to master file
                master_file = os.path.join(lib_path, f"{lib_name}.kicad_sym")
                with open(master_file, "r+", encoding="utf-8") as mf:
                    m_cont = mf.read()
                    if f'(symbol "{pcode}"' not in m_cont:
                        last_p = m_cont.rfind(')')
                        new_m = m_cont[:last_p] + "  " + block + "\n" + m_cont[last_p:]
                        mf.seek(0); mf.write(new_m); mf.truncate()
                return block
        except Exception as e:
            self._log(f"Extract sym error: {e}")
            return None

    def consolidate_footprint_to_master(self, lib_path, pcode, master_fp_dir, lib_name):
        try:
            temp_fp_dir = os.path.join(lib_path, f"_tmp_{pcode}.pretty")
            temp_3d_dir = os.path.join(lib_path, f"_tmp_{pcode}.3dshapes")
            master_3d_dir = os.path.join(lib_path, f"{lib_name}.3dshapes")
            
            if not os.path.exists(master_3d_dir):
                os.makedirs(master_3d_dir, exist_ok=True)

            model_filenames = []
            
            # 1. Mover modelos 3D
            if os.path.exists(temp_3d_dir):
                for f in os.listdir(temp_3d_dir):
                    if f.endswith(".step") or f.endswith(".wrl") or f.endswith(".stp"):
                        ext = os.path.splitext(f)[1]
                        model_filename = f"{pcode}{ext}"
                        model_filenames.append(model_filename)
                        old_path = os.path.join(temp_3d_dir, f)
                        new_path = os.path.join(master_3d_dir, model_filename)
                        if os.path.exists(new_path): os.remove(new_path)
                        shutil.copy2(old_path, new_path)

            # 2. Mover huella y arreglar referencia 3D
            if os.path.exists(temp_fp_dir):
                for f in os.listdir(temp_fp_dir):
                    if f.endswith(".kicad_mod"):
                        old_path = os.path.join(temp_fp_dir, f)
                        new_path = os.path.join(master_fp_dir, f"{pcode}.kicad_mod")
                        if os.path.exists(new_path): os.remove(new_path)
                        
                        with open(old_path, "r", encoding="utf-8") as fp_file:
                            content = fp_file.read()
                            
                            # Si detectamos un modelo 3D, corregimos la ruta en la huella
                            if model_filenames:
                                # easyeda2kicad pone algo como (model "ruta")
                                # Lo reemplazamos por la ruta consolidada
                                new_model_path = f"${{KIPRJMOD}}/{lib_name}/{lib_name}.3dshapes/{model_filenames[0]}"
                                content = re.sub(r'\(model\s+"[^"]+"', f'(model "{new_model_path}"', content)
                        
                        with open(new_path, "w", encoding="utf-8") as fp_file:
                            fp_file.write(content)
        except Exception as e:
            self._log(f"Consolidate fp/3d error: {e}")

    def inject_symbol_to_cache(self, project_path, pcode, symbol_block, lib_name):
        cache_block = symbol_block.replace(f'(symbol "{pcode}"', f'(symbol "{lib_name}:{pcode}"')
        sch_path = self.get_sch_path(project_path)
        if not sch_path: return
        with open(sch_path, "r", encoding="utf-8") as f:
            content = f.read()
            if f'symbol "{lib_name}:{pcode}"' in content: return
            marker = "(lib_symbols)"
            if marker in content:
                new_c = content.replace(marker, f"(lib_symbols\n    {cache_block}\n  )")
            else:
                start_lib = content.find("(lib_symbols")
                if start_lib != -1:
                    p_count = 0
                    for i in range(start_lib, len(content)):
                        if content[i] == '(': p_count += 1
                        elif content[i] == ')':
                            p_count -= 1
                            if p_count == 0:
                                new_c = content[:i] + f"    {cache_block}\n  " + content[i:]; break
                else: return
            with open(sch_path, "w", encoding="utf-8") as fw: fw.write(new_c)

    def _find_symbol_block_by_uuid(self, content, u_id):
        uuid_str = f'uuid "{u_id}"'
        start_idx = content.find(uuid_str)
        if start_idx == -1:
            return None, -1, -1

        # Walk backwards from start_idx to find the (symbol ... (lib_id ... block start
        pos = content.rfind("(symbol", 0, start_idx)
        block_start = -1
        while pos != -1:
            snippet = content[pos:start_idx]
            if re.search(r'\(symbol\s+\(lib_id', snippet):
                block_start = pos
                break
            pos = content.rfind("(symbol", 0, pos)

        if block_start == -1:
            return None, -1, -1

        # Parse balanced parentheses to find block end
        p_count = 0
        block_end = -1
        in_quote = False
        escaped = False

        for i in range(block_start, len(content)):
            char = content[i]
            if char == '"' and not escaped:
                in_quote = not in_quote
            if not in_quote:
                if char == '(':
                    p_count += 1
                elif char == ')':
                    p_count -= 1
                    if p_count == 0:
                        block_end = i + 1
                        break
            if char == '\\' and not escaped:
                escaped = True
            else:
                escaped = False

        if block_end == -1:
            return None, -1, -1

        return content[block_start:block_end], block_start, block_end

    def get_instance_info_by_uuid(self, project_path, u_id):
        sch_path = self.get_sch_path(project_path)
        if not sch_path: return None
        try:
            with open(sch_path, "r", encoding="utf-8") as f:
                content = f.read()
            block, _, _ = self._find_symbol_block_by_uuid(content, u_id)
            if not block: return None
            match = re.search(r'\(property\s+"Reference"\s+"([^"]+)"', block)
            return match.group(1) if match else None
        except Exception as e:
            self._log(f"get_instance_info_by_uuid error: {e}")
            return None

    def remove_instance_by_uuid(self, project_path, u_id):
        sch_path = self.get_sch_path(project_path)
        if not sch_path: return False
        try:
            with open(sch_path, "r", encoding="utf-8") as f:
                content = f.read()
            
            block, block_start, block_end = self._find_symbol_block_by_uuid(content, u_id)
            if block_start == -1 or block_end == -1: return False

            new_content = content[:block_start] + content[block_end:]
            # Clean up potential double newlines
            new_content = new_content.replace("\n\n\n", "\n\n")
            with open(sch_path, "w", encoding="utf-8") as f:
                f.write(new_content)
            self._log(f"Physically removed instance {u_id} from schematic.")
            return True
        except Exception as e:
            self._log(f"Remove instance error: {e}")
            return False

    def get_all_placed_jlc_symbols(self, project_path):
        sch_path = self.get_sch_path(project_path)
        if not sch_path or not os.path.exists(sch_path): return []
        try:
            with open(sch_path, "r", encoding="utf-8") as f:
                content = f.read()

            pos = content.find("(symbol")
            symbols_found = []

            while pos != -1:
                snippet = content[pos:pos+200]
                if re.search(r'\(symbol\s+\(lib_id', snippet):
                    p_count = 0; block_end = -1; in_quote = False; escaped = False
                    for i in range(pos, len(content)):
                        char = content[i]
                        if char == '"' and not escaped: in_quote = not in_quote
                        if not in_quote:
                            if char == '(': p_count += 1
                            elif char == ')':
                                p_count -= 1
                                if p_count == 0: block_end = i + 1; break
                        if char == '\\' and not escaped: escaped = True
                        else: escaped = False

                    if block_end != -1:
                        block = content[pos:block_end]
                        uuid_m = re.search(r'\(uuid\s+"([^"]+)"', block)
                        jlc_m = re.search(r'\(property\s+"JLCPCB Part #"\s+"([^"]+)"', block) or re.search(r'\(property\s+"LCSC Part #"\s+"([^"]+)"', block)
                        ref_m = re.search(r'\(property\s+"Reference"\s+"([^"]+)"', block)
                        val_m = re.search(r'\(property\s+"Value"\s+"([^"]+)"', block)
                        fp_m = re.search(r'\(property\s+"Footprint"\s+"([^"]+)"', block)
                        mfr_m = re.search(r'\(property\s+"Manufacturer"\s+"([^"]+)"', block)

                        if uuid_m and jlc_m:
                            symbols_found.append({
                                "uuid": uuid_m.group(1),
                                "pcode": jlc_m.group(1),
                                "ref": ref_m.group(1) if ref_m else "",
                                "val": val_m.group(1) if val_m else "",
                                "fp": fp_m.group(1) if fp_m else "",
                                "mfr": mfr_m.group(1) if mfr_m else "N/A"
                            })
                        pos = block_end - 1

                pos = content.find("(symbol", pos + 1)
            return symbols_found
        except Exception as e:
            self._log(f"get_all_placed_jlc_symbols error: {e}")
            return []

    def inject_instance_to_schematic(self, project_path, pcode, model_name, lib_name, prefix="U", manufacturer="N/A"):

        sch_path = self.get_sch_path(project_path)
        if not sch_path: return None
        try:
            with open(sch_path, "r", encoding="utf-8") as f:
                content = f.read()
                
                # 1. Smart Auto-Annotation
                existing_refs = re.findall(rf'\(property\s+"Reference"\s+"{prefix}(\d+)"', content)
                existing_nums = [int(n) for n in existing_refs]
                next_num = max(existing_nums + [0]) + 1
                ref_designator = f"{prefix}{next_num}"

                # 2. Position calculation
                count = len(re.findall(r'\(symbol\s+\(lib_id', content))
                x, y = 100 + (count % 10) * 40, 100 + (count // 10) * 40
                u_id = str(uuid.uuid4())
                
                sch_uuid_match = re.search(r'\(uuid\s+"(.*?)"\)', content)
                sch_uuid = sch_uuid_match.group(1) if sch_uuid_match else str(uuid.uuid4())
                
                proj_name_raw = os.path.basename(project_path)
                proj_name = proj_name_raw.replace(".kicad_pro", "").replace(".kicad_sch", "")

                # Extra Professional Fields for SMT/BOM
                f_jlc = f'    (property "JLCPCB Part #" "{pcode}" (at {x} {y} 0) (effects (font (size 1.27 1.27)) hide))\n'
                f_lcsc = f'    (property "LCSC Part #" "{pcode}" (at {x} {y} 0) (effects (font (size 1.27 1.27)) hide))\n'
                f_mfr = f'    (property "Manufacturer" "{manufacturer}" (at {x} {y} 0) (effects (font (size 1.27 1.27)) hide))\n'

                sym_entry = f'\n  (symbol (lib_id "{lib_name}:{pcode}") (at {x} {y} 0) (unit 1)\n' \
                            f'    (in_bom yes) (on_board yes) (uuid "{u_id}")\n' \
                            f'    (property "Reference" "{ref_designator}" (at {x} {y-5} 0) (effects (font (size 1.27 1.27))))\n' \
                            f'    (property "Value" "{model_name}" (at {x} {y+5} 0) (effects (font (size 1.27 1.27))))\n' \
                            f'    (property "Footprint" "{lib_name}:{pcode}" (at {x} {y} 0) (effects (font (size 1.27 1.27)) hide))\n' \
                            f'{f_jlc}{f_lcsc}{f_mfr}' \
                            f'    (instances\n' \
                            f'      (project "{proj_name}"\n' \
                            f'        (path "/{sch_uuid}" (reference "{ref_designator}") (unit 1))\n' \
                            f'      )\n' \
                            f'    )\n' \
                            f'  )\n'
                last_p = content.rfind(')')
                new_c = content[:last_p] + sym_entry + content[last_p:]
                with open(sch_path, "w", encoding="utf-8") as fw: fw.write(new_c)
                self._log(f"Injected {ref_designator} with value {model_name} to schematic.")
                return u_id
        except Exception as e:
            self._log(f"Inject instance error: {e}")
            return None

