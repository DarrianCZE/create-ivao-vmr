

# create-ivao-vmr
Create a vPilot VMR file from the IVAO MTL library.  
**NEW**: This script now supports creating a VMR from the Alpha India Group (AIG) traffic library.
**NEW**: This script automatically exports to your Documents/vPilot Files folder.

## Usage
Requires [Python](https://www.python.org/).  

#### IVAO MTL:
Make sure to [download](https://mtl.ivao.aero/installer), install, and index the IVAO MTL.  
Drop the `create_vmr.py` file in your `Packages/Community/IVAO_MTL` folder.  
Open a Windows Terminal and enter `python create_vmr.py`.  
Wait for the script to finish. It should only take a few seconds (less than two for me).  
The VMR file will be created as "ivaomtl.vmr" in the folder as the python script.  

#### AIG
Make sure to [download](https://www.alpha-india.net/) and install the AIG library.  
Drop the `create_vmr.py` file in your `Packages/Community/aig-aitraffic-oci-beta` folder.  
Open a Windows Terminal and enter `python create_vmr.py -l aig`.  
Wait for the script to finish. It should only take a few seconds (less than two for me).  
The VMR file will be created as "aig.vmr" in the folder as the python script.  

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


`-p | --output-directory` default: ~/Documents/vPilot Files  
Set the output directory for the VMR. The default location is the normal vPilot Files directory. Ensure you wrap the entire path in "quotation marks".
 

`-v | -verbose`  
More verbose logging of what's going on. Get a real sense of speed. Makes you feel like your computer is super duper fast.

`-s | --standard-only`  
Only use the standard livery of each airline. The IVAO MTL contains many special, retro, alliance and event liveries (in the [MTL catalog](https://mtl.ivao.aero/catalog) these have a number at the end of the MTLID, for example `A320EWG2` = Eurowings Europa Park, while `A320EWG` is the normal Eurowings livery). vPilot picks one of the listed models at random, so an airline with one standard and three special liveries shows up in a special livery most of the time. With this option the special liveries are left out, so aircraft appear in the normal colours of their airline.  
If an airline only has special liveries for a given aircraft type, those are kept, because a special livery is still a better match than a generic aircraft. The script prints how many liveries were left out and how many were kept for this reason. This option only applies to the IVAO library.

`-n | --no-pause`  
By default the script waits for you to press Enter before it closes, so the output can be read when the script is started by double-clicking it. Use this option to skip the pause (for example when running the script from a batch file).

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