# Architecture diagram

The picture in the top-level [README](../README.md) is generated, not drawn. This folder
holds the generator and its output.

| File | What it is |
| --- | --- |
| `build_architecture.py` | The generator. Edit the lists at the top, then rerun. |
| `cloudicons.py` | Resolves a service name to an official Azure or Fabric icon. |
| `render.py` | Turns the SVG into a PNG using headless Chrome or Edge. |
| `brand-icons/` | Third-party logos that are not in the Microsoft sets. |
| `powerbi-ai-demo-architecture.drawio` | Editable source. Open in draw.io. |
| `powerbi-ai-demo-architecture.svg` | Standalone vector. |
| `powerbi-ai-demo-architecture.png` | What the README shows. |

## You do not need anything installed to use it

The `.drawio` and `.svg` embed every icon as a base64 data URI, and the `.png` is a
raster of that same self-contained SVG. All three open offline, with no CDN and no icon
set on your machine. Clone the repo and the diagram just works.

You only need the icon sets to **regenerate** it.

## Regenerating

Point two environment variables at your local icon sets:

| Set | Variable | Where to get it |
| --- | --- | --- |
| Azure | `AZURE_ICONS_DIR` | [Azure architecture icons](https://learn.microsoft.com/azure/architecture/icons/), the `Azure_Public_Service_Icons` folder |
| Fabric | `FABRIC_ICONS_DIR` | `npm install @fabric-msft/svg-icons`, then point at `node_modules/@fabric-msft/svg-icons/svg` |

If you leave them unset they fall back to `~/Azure_Public_Service_Icons` and
`~/Fabric_Icons`.

```powershell
$env:AZURE_ICONS_DIR  = "$HOME\Azure_Public_Service_Icons"
$env:FABRIC_ICONS_DIR = "$HOME\Fabric_Icons"

python diagram/build_architecture.py
python diagram/render.py diagram/powerbi-ai-demo-architecture.svg --png-only
```

The generator **fails loudly** if an icon does not resolve, rather than writing a diagram
with a hole in it.

## Finding an icon

```powershell
python diagram/cloudicons.py "lakehouse" --provider fabric
python diagram/cloudicons.py "azure openai" --json
python diagram/cloudicons.py --list --provider fabric
```

Two traps worth knowing:

1. **draw.io's built-in Azure stencils have no Fabric item icons.** No Lakehouse, no
   Warehouse, no Semantic model, no Notebook. If you picked a Fabric item from that set,
   you picked the wrong product. This script exists to fix that.
2. **GitHub Copilot and Microsoft Copilot are different products with different marks.**
   Use `--provider brand` for GitHub Copilot, and the official Fabric `copilot` icon for
   Copilot in Power BI.

## Changing it

Edit `COLUMNS`, `BAND_CARDS` or `FLOW` at the top of `build_architecture.py`, regenerate,
then **open the PNG and look at it**. Card subtitles are hand-wrapped as a list of lines,
so a longer string will overflow rather than wrap.

The [`solution-architect`](../.github/agents/solution-architect.agent.md) agent does all
of this for you, including adapting the diagram to a different dataset or capacity.

## Licence and trademark

`cloudicons.py` and `render.py` are vendored under MIT. The Azure and Fabric icons are
Microsoft trademarks. The icon **sets** are not vendored here, but individual icons are
embedded in the generated `.drawio`, `.svg` and `.png` for identification only, and are
not covered by this repo's MIT licence. Their use is governed by the
[Microsoft icon terms](https://learn.microsoft.com/azure/architecture/icons/).
Third-party logos in `brand-icons/` are covered by
[`brand-icons/NOTICE.md`](brand-icons/NOTICE.md).
