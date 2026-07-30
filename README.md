# JLC Library Gen

**JLC Library Gen** is a powerful KiCad plugin designed to streamline the process of searching, managing, and injecting JLCPCB/LCSC components directly into your KiCad schematic. It bridges the gap between the JLCPCB parts database and your design workflow, handling symbol and footprint generation automatically.

##  Features

- **Direct JLCPCB Search:** Search the entire JLCPCB SMT parts library without leaving KiCad.
- **Visual Preview:** High-quality image previews of components and CAD renders for symbols and footprints.
- **Smart Injection:** Automatically injects components into your KiCad schematic with correct footprints and metadata (JLCPCB Part #, Manufacturer, etc.).
- **Quantity Management:** Track and adjust component quantities directly within the plugin.
- **Global Library:** Save your favorite parts to a global library for use across different projects.
- **Automated CAD Sync:** Automatically downloads and consolidates symbols/footprints into your project's local library.

##  Screenshots

<img width="1286" height="884" alt="image" src="https://github.com/user-attachments/assets/448e8cb8-2283-4c42-9c55-3841efa3e18e" />


##  Installation

1. Clone this repository or download the ZIP:
   ```bash
   git clone https://github.com/NoNamedCat/JLC_Library_Gen.git
   ```
2. Copy the `kicad_jlcpcb_search` folder to your KiCad 3rd party plugins directory:
   - **Windows:** `%APPDATA%\kicad\10.0\3rdparty\plugins\`
   - **macOS:** `~/Library/Preferences/kicad/10.0/3rdparty/plugins/`
   - **Linux:** `~/.local/share/kicad/10.0/3rdparty/plugins/`
3. Restart KiCad or refresh plugins in the PCB Editor.

##  How to Use

1. Open the **PCB Editor** in KiCad.
2. Click the **JLC Library Gen** icon in the toolbar.
3. Use the search bar to find components (e.g., "10k 0603").
4. Select a part to see its technical properties, photo, and CAD preview.
5. Click **ADD TO LIST >>** to include it in your project.
6. In the **PROJECT COMPONENTS** section, use `+` or `-` to adjust quantities.
7. Click **ADD CART TO PROJECT** to automatically download the models and inject them into your schematic.

##  Requirements

- KiCad 10.0 or higher.
- Python 3 with `requests` and `wxPython` (included with KiCad's internal Python).
- `easyeda2kicad` (automatically handled or manually installable via pip).

##  License

This project is licensed under the MIT License - see the LICENSE file for details.

---
*Created by [NoNamedCat](https://github.com/NoNamedCat)*
