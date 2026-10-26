

# create-ivao-vmr
Create a vPilot VMR file from the IVAO MTL library.  
**NEW**: This script now supports creating a VMR from the Alpha India Group (AIG) traffic library.
The script writes its files to the folder you run it from. Use `-p` to export straight to your Documents/vPilot Files folder.

## Usage
Requires [Python](https://www.python.org/).  

#### IVAO MTL:
Make sure to [download](https://mtl.ivao.aero/installer), install, and index the IVAO MTL.  
Drop the `create_vmr.py` file in your `Packages/Community/IVAO_MTL` folder.  
Open a Windows Terminal and enter `python create_vmr.py`.  
Wait for the script to finish. It should only take a few seconds (less than two for me).  
The script creates three files in the folder you run it from (the `IVAO_MTL` folder):

- `ivaomtl.vmr`: the complete VMR with every livery in the MTL.
- `ivaomtl_standard.vmr`: the same rules, but with only the standard livery of each airline. The IVAO MTL contains many special, retro, alliance and event liveries next to the normal airline livery. vPilot picks one of the listed models at random, so an airline with one standard and three special liveries shows up in a special livery most of the time. In this VMR the special liveries are left out, so aircraft appear in the normal colours of their airline. Use either this file or `ivaomtl.vmr` in vPilot, not both.
- `ivaomtl_liveries.csv`: one line per livery with the MTL ID, airline, aircraft type, texture, livery name and whether the standard-only VMR treats it as standard or special. Useful to check which liveries are left out.

The standard livery is recognised by its name from the [MTL catalog](https://mtl.ivao.aero/catalog), which the MTL stores in the `ui_variation` entry of each livery: `Air Canada (ACA)` is the standard livery, `Air Canada (old colors) (ACA)` or `Lufthansa (Star Alliance) (DLH)` are special ones. Descriptions that only name the engines or winglets of the model (`(CFM)`, `(IAE)`, `(WL)`) or say that it is the airline's new scheme (`(NC)`, `(New Colors)`) still count as standard. If a livery has no name, the texture name decides: `EWG` is standard, `EWG2` is special. If an airline only has special liveries for a given aircraft type, those are kept, because a special livery is still a better match than a generic aircraft. The script prints how many liveries were left out and how many were kept for this reason.  

#### AIG
Make sure to [download](https://www.alpha-india.net/) and install the AIG library.  
Drop the `create_vmr.py` file in your `Packages/Community/aig-aitraffic-oci-beta` folder.  
Open a Windows Terminal and enter `python create_vmr.py -l aig`.  
Wait for the script to finish. It should only take a few seconds (less than two for me).  
The VMR file will be created as "aig.vmr" in the folder you run the script from.  

#### Recommended VMR Order
You can place your VMR files in any order you wish in vPilot.  
I recommend the following order:
```
FSLTL
AIG (this script's output)
IVAO MTL (this script's output)
British Avgeek's VMR
```
I recommend placing [British Avgeek's VMR (download)](https://flightsim.to/file/23365/full-vatsim-aig-beta-model-matching) at the end since it contains many substitutions, such as replacing the FedEx B722 with the B763 instead. This is very convenient and desirable as a fallback, but placing his VMR at the end of the list makes it more likely that we will see the correct models. In this example vPilot's model matching will be as follows:
```
FSLTL: no FDX B722 --skip--
AIG: no FDX B722 --skip--
IVAO MTL: FDX B722 found! (vPilot will use this)
British Avgeek VMR: FDX B722 found! (shows as B763, skipped since IVAO is already being used.)
```

### Options
`-d | --directory [path]` default: "./SimObjects/Airplanes"  
Specify a path where the script will look for the model files. The path specified should contain the `SimObjects/Airplanes` folder. Make sure to put the path in quotation marks.  


`-l (lower-case L) | -library ["ivao" || "aig"]` default: ivao  
Set which model-matching library you're using. Default is IVAO MTL. Use "aig" for the AIG library.


```bash
-o | --output [file]
# default: ivaomtl.vmr
# python create_vmr.py -o "C:\Users\mydir\Documents\vPilot Files/out.vmr"
# python create_vmr.py -o ivaomtl.vmr
```
Specify the output of the script. If you specify a directory, make sure to wrap it in quotation marks.  
For the IVAO library the standard-only VMR and the livery list take their names from this file: `-o my.vmr` creates `my.vmr`, `my_standard.vmr` and `my_liveries.csv`.  


`-p | --output-directory` default: the folder you run the script from  
Set the output directory for all files, for example `-p "C:\Users\mydir\Documents\vPilot Files"` to export straight to vPilot. Ensure you wrap the entire path in "quotation marks".
 

`-v | -verbose`  
More verbose logging of what's going on. Get a real sense of speed. Makes you feel like your computer is super duper fast.

`-n | --no-pause`  
By default the script waits for you to press Enter before it closes, so the output can be read when the script is started by double-clicking it. Use this option to skip the pause (for example when running the script from a batch file).

## GUI: build your own VMR with presets and the MTL rules
`vmr_gui.py` is a small graphical front end for building a VMR out of three parts: ready-made presets, your own rules, and the rules generated from your MTL (the same ones `create_vmr.py` makes). The presets and your rules are meant for what the MTL-generated file does not contain: airline groups that share liveries (for example the Smartwings group flying Czech Airlines colours), wet-lease operators, or liveries you want to see instead of the default one. They come first in the file, so they win in vPilot.

**Portable .exe (no Python, no installation):** download `IVAO_VMR_Generator.exe` from the [releases](https://github.com/vojta48/create-ivao-vmr/releases) (or from the *Build portable exe* run under *Actions*), put it into your `Packages/Community/IVAO_MTL` folder and double-click it. The GUI opens in its own window (it uses the Microsoft Edge WebView2 runtime that is part of Windows 10 and 11). If something goes wrong, the program shows a message and writes the details to `vmr_gui.log` next to the .exe. The `gui` and `presets` folders are packed inside the .exe. To add your own presets, create a `presets` folder next to the .exe and put your `.vmr` files there. Windows SmartScreen may warn about an unknown publisher because the file is not signed; choose *More info → Run anyway*.

**From source:** drop `vmr_gui.py`, the `gui` folder and the `presets` folder into your `Packages/Community/IVAO_MTL` folder (next to `create_vmr.py`) and run:
```
python vmr_gui.py
```
With `pip install pywebview` the GUI opens in its own window; without it, it opens in your browser (http://127.0.0.1:8765). `--browser` forces the browser. In the GUI you can:

- **Tick presets**: every `.vmr` file in the `presets` folder is offered as a ready-made rule set. Two are included: `smartwings_group.vmr` (Smartwings, Smartwings Poland/Hungary/Slovakia and Czech Airlines sharing the Smartwings fleet) and `extra_rules.vmr` (liveries missing from the MTL, substituted with a similar one). Add your own `.vmr` files to the folder to offer them as presets; a `<!-- comment -->` in the file is shown as its description.
- **Write your own rules**: one line per `ModelMatchRule` with the callsign prefix (3-letter airline code, empty for any callsign), the ICAO type and the MTL livery ids. Several liveries are separated with `//`, vPilot then picks one at random. Rules can also be imported from an existing VMR file.
- **Add the MTL rules**: tick *Add the rules generated from my MTL* and choose *standard liveries only* (what `create_vmr.py` writes to `ivaomtl_standard.vmr`, see above) or *all liveries* (`ivaomtl.vmr`). They are appended after the presets and your rules, so one file is enough in vPilot. Optionally the livery list (`<name>_liveries.csv`) is written next to it.
- **See the liveries**: the right column lists every livery installed in your MTL with its catalog name, type and airline, and marks the special liveries. Search by airline, type, id or name and click a livery to add it to the rule you are editing. The ↗ next to a livery opens it in the [MTL catalog](https://mtl.ivao.aero/catalog), where you can see its picture. Each rule links its liveries the same way and warns about ids that are not installed.
- **Save**: the result is written to the folder you run the script from (or `-p`), or saved through a file dialog. Add the file in vPilot under *Settings → Model Matching → Custom Rules*: with the MTL rules included it replaces the IVAO MTL VMR, without them move it above the IVAO MTL VMR, so that its rules win.

The GUI does not show pictures of the liveries: the thumbnails inside the MTL packages are one generic picture for every livery, and the pictures of the catalog can only be found through the IVAO API, which needs an API key.

Options: `-d` the folder that contains `SimObjects/Airplanes` (default: the current folder, for the .exe the folder it lies in), `-p` the output folder, `--port` the port of the local server, `--browser` to use the web browser instead of the window, `--no-browser` to only run the server.

Building the .exe yourself: `pip install pyinstaller pywebview` and `pyinstaller build_exe.spec` on Windows; the result is `dist/IVAO_VMR_Generator.exe`. The GitHub Actions workflow `build-exe.yml` does the same on every push and attaches the file to the release when a `v*` tag is pushed.

## Code signing policy
Free code signing provided by [SignPath.io](https://signpath.io), certificate by [SignPath Foundation](https://signpath.org).

The Windows executable `IVAO_VMR_Generator.exe` attached to a [release](https://github.com/vojta48/create-ivao-vmr/releases) is digitally signed, so that Windows can verify who published the file and that it was not changed after the build. To check the signature, open the file's *Properties → Digital Signatures* in Windows Explorer, or run `Get-AuthenticodeSignature IVAO_VMR_Generator.exe` in PowerShell. The signer is *SignPath Foundation*. An executable that is not signed (a workflow artifact of a pull request, or a build you made yourself) should only be used if you built it or trust where it came from.

**How a release is built and signed.** Every release is built by [GitHub Actions](https://github.com/vojta48/create-ivao-vmr/actions/workflows/build-exe.yml) from the source code of this repository (`build-exe.yml` and `build_exe.spec`), never on a developer's computer. SignPath verifies that the executable comes from this repository's build, and the signing request is then approved by hand by an approver listed below. Every signing request requires this manual approval. The private key is kept in SignPath's hardware security module; nobody involved in the project has it.

**Team roles.** Changes from anyone outside the team are reviewed before they are merged.

| Role | Members |
| --- | --- |
| Committers and reviewers | [vojta48](https://github.com/vojta48) |
| Approvers | [vojta48](https://github.com/vojta48) |

**Privacy policy.** The program runs entirely on your computer. It does not collect, store or send any personal data, usage statistics or crash reports. It does not connect to the internet by itself; clicking a livery link opens `mtl.ivao.aero` in your browser, which is covered by [IVAO's privacy policy](https://ivao.aero/privacy).

**Reporting a problem.** If you think a signed release contains something it should not, do not run it and open an [issue](https://github.com/vojta48/create-ivao-vmr/issues) with the file's SHA256 hash and where you downloaded it.

## Log file
Everything the script prints is also written to `create_vmr.log` in the folder the script is run from. If the script crashes, the full error is in that file. Please attach it when reporting a problem.


## I got an error when I ran the script!
### The error mentions an issue with "[VERSION]"
This error occurs due to a bug with the IVAO MTL installation: some `aircraft.cfg` files contain a section header written as `VERSION]` instead of `[VERSION]`.  
The `create_vmr.py` script now fixes this automatically. Before reading each `aircraft.cfg` it checks for a line that says `VERSION]` and adds the missing `[`. Nothing else in the file is changed. The script prints a list of the files it fixed at the end of the run.  
If you still get the error (for example because the file is read-only), you can fix it by hand as described below.  
Some of these files also contain a second `[VERSION]` section once the header is fixed. The script reads `aircraft.cfg` files in a tolerant mode, so a duplicated section or option no longer causes an error.  
The error should look like this:  
![](https://i.imgur.com/PCx8Q4G.png)    
In this case, navigate to the file listed in the error. Open the file and scroll all the way to the bottom. Near the bottom, we see this:   
![](https://i.imgur.com/0EVfEq5.png)  
We can fix the problem by added the missing `[` to the beginning of where it says `VERSION]`. It should look like this:  
![](https://i.imgur.com/PZIfCds.png)  
Great! Now rerun the script with `python create_vmr.py`. This time there should be no errors.  

### I got a different error!
No problem! Head to the top of this page, click "Issues" and open a new issue.