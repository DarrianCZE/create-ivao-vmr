# This script creates a VMR file from the IVAO MTL model matching library.
# Run this script from the root folder of the MTL library "Packages/Community/IVAO_MTL"
# The output file is titled "ivaomtl.vmr" and is placed in this directory.
# Script by github.com/andrewward2001

import configparser
import getopt
import os
import re
from pathlib import Path
import sys
import traceback
from collections import defaultdict

verbose = False
models_directory = "./SimObjects/Airplanes"
# All files are written to the folder the script is run from (the MTL folder), unless -p says otherwise.
output_directory = Path(".")
output_file = "ivaomtl.vmr"
log_file = "create_vmr.log"
lib = "ivao"
pause_at_end = True
# For the IVAO library the script writes three files next to each other in output_directory:
#   <output_file>            the complete VMR with every livery
#   <stem>_standard.vmr      the VMR with the standard airline liveries only
#   <stem>_liveries.csv      the list of all liveries with their names
# excluded_types = ["A4", "B1", "B2", "BE12", "BE35", "BE36", "BE40", "BE60", "C152", "C172", "C207"]

errored_files = []
fixed_files = []
special_titles = set()
livery_info = {}
special_skipped = 0
special_kept = 0
kept_titles = set()
model_list_len = 0
texture_len = 0
airlines_len = 0
rules_len = 0

# Everything printed to the console is also written to the log file, so the output can be read
# even when the script is started by double-clicking it and the window closes right away.
class Tee:
    def __init__(self, *streams):
        self.streams = streams
    def write(self, data):
        for stream in self.streams:
            try:
                stream.write(data)
                stream.flush()
            except Exception:
                pass
    def flush(self):
        for stream in self.streams:
            try:
                stream.flush()
            except Exception:
                pass

# The command line part (log file, options) runs only when the script is started directly.
# vmr_gui.py imports this file to reuse the livery rules below without running anything.
def parse_command_line():
    global verbose, models_directory, output_directory, output_file, lib, pause_at_end
    try:
        log = open(log_file, "w", encoding="utf-8")
        sys.stdout = Tee(sys.__stdout__, log)
        sys.stderr = Tee(sys.__stderr__, log)
        print("Log file: " + os.path.abspath(log_file))
    except OSError as err:
        print("Could not create log file " + log_file + ": " + str(err))

    argsList = sys.argv[1:]
    options = "d:o:vl:p:n"
    long_options = ['directory=', 'output=', 'verbose', 'library=', 'output-directory=', 'no-pause']

    try:
        arguments, values = getopt.getopt(argsList, options, long_options)

        for currentArgument, currentValue in arguments:
            if currentArgument in ("-d", "--directory"):
                models_directory = currentValue
                print("Reading from " + currentValue)
            elif currentArgument in ("-l", "--library"):
                if currentValue == "ivao":
                    lib = "ivao"
                elif currentValue == "aig":
                    lib = "aig"
                    output_file = "aig.vmr"
                else:
                    print("Error! Library can only be either \"ivao\" or \"aig\"")
                    exit()
            elif currentArgument in ("-o", "--output"):
                output_file = currentValue
            elif currentArgument in ("-v", "--verbose"):
                verbose = True
            elif currentArgument in ("-p", "--output-directory"):
                output_directory = Path(currentValue)
            elif currentArgument in ("-n", "--no-pause"):
                pause_at_end = False

        print("Output to: " + os.path.abspath(output_directory / output_file))
    except getopt.error as err:
        print(err)

# Creates the string that will be output on each new line of the VMR to act as a Rule.
# callsign: String referring to the 3-letter ICAO identifier used in a callsign (ex. AAL, DAL, UAL, BAW, etc.)
# type: String referring to the ICAO aircraft type identifier (ex. B738, A320, B77W)
# modeltitle: String referring to which model vPilot should load. This string must match the "title" entry under [fltsim.n] in the aircraft.cfg file
def build_rule(callsign, type, modeltitle):
    # <ModelMatchRule CallsignPrefix="BAW" TypeCode="B733" ModelName="F1UT2_733.BA.BA" />
    out = "<ModelMatchRule"

    # If the callsign is blank, "def" (default), or ZZZZ, then the rule isn't associated with an airline. By leaving out the "CallsignPrefix" vPilot will only match against the aircraft type and not the callsign.
    # The if statement is written this way because I am bad at python and this is the only way I could get it to work.
    if callsign == "" or callsign == "def" or type == "ZZZZ":
        # do nothing
        out = out + ""
    else:
        out = out + " CallsignPrefix=\"" + callsign + "\""
    out = out + " TypeCode=\"" + type + "\" ModelName=\"" + modeltitle + "\" /> \n"
    return out

# Ensures that callsign entries are 3-letter airline identifiers. Otherwise, leave this blank.
def determine_callsign_prefix(entry):
    global lib
    if lib == "aig":
        try:
            return entry["icao_airline"]
        except:
            return ""
    if lib == "ivao":
        if "\"" not in entry["texture"][1:4]:
            return entry["texture"][1:4]
        else:
            return ""
        
# Decides whether a livery is the standard airline livery or a special / alternative one.
#
# The IVAO MTL puts the livery name from the MTL catalog into ui_variation, in the form
#   ui_variation="Air Canada (ACA)"                  -> the standard livery
#   ui_variation="Air Canada (old colors) (ACA)"     -> an alternative livery
#   ui_variation="Lufthansa (Star Alliance) (DLH)"   -> an alternative livery
# The last group in brackets is the airline code; every group before it describes what is special about the livery.
# A livery without such a group is the standard livery. A few descriptions do not make a livery special: they only
# say which engines or winglets the model has, or that it is the airline's new scheme. Those are listed below.
#
# If there is no ui_variation (older packages), the texture name decides instead: in the catalog the standard
# livery has no number (A320EWG = Eurowings, A320EWG2 = Eurowings Europa Park), and the texture name in the
# aircraft.cfg follows the same convention (texture="EWG" vs texture="EWG2").
NEUTRAL_QUALIFIERS = re.compile(
    r"^(cfm|iae|pw|p&w|pratt ?& ?whitney|rr|rolls[ -]?royce|ge|trent|leap|neo|ceo)( engines?)?$"
    r"|^(nc|new( colou?rs| livery| scheme)?|current( colou?rs| livery)?)$"
    r"|^(wl|(blended |split |scimitar )?winglets|sharklets)$"
)

def livery_name_parts(ui_variation):
    name = ui_variation.strip().strip("\"")
    groups = re.findall(r"\(([^()]*)\)", name)
    base = re.sub(r"\s*\([^()]*\)", "", name).strip()
    airline = ""
    if len(groups) > 0 and re.fullmatch(r"[A-Z0-9]{3}", groups[-1].strip()):
        airline = groups.pop().strip()
    return base, [g.strip() for g in groups], airline

def is_standard_livery(texture_name, ui_variation):
    if ui_variation.strip().strip("\"") != "":
        base, qualifiers, airline = livery_name_parts(ui_variation)
        return all(NEUTRAL_QUALIFIERS.match(q.lower()) for q in qualifiers)
    name = texture_name.strip().strip("\"")
    return re.search(r"[0-9]", name) is None

# Depending on if we are creating a VMR from the IVAO MTL or the AIG models, the aircraft type is located at a different part of the aircraft.cfg.
def determine_aircraft_type(config, section):
    global lib
    if lib == "aig":
        for mSection in config.sections():
            try:
                if "general" in mSection:
                    return config["general"]["icao_type_designator"][1:-1]
                elif "General" in mSection:
                    return config["General"]["icao_type_designator"][1:-1]
                elif "GENERAL" in mSection:
                    return config["GENERAL"]["icao_type_designator"][1:-1]
            except:
                return ""
        return ""
    else:
        return config[section]["ui_type"][1:5]
    

# Some IVAO MTL aircraft.cfg files ship with a broken section header "VERSION]" (missing the opening "[").
# configparser refuses to parse such a file, so the whole model would be left out of the VMR.
# This function fixes only that one problem: lines that read "VERSION]" are rewritten as "[VERSION]".
# The file is handled as raw bytes so the encoding, line endings and every other line stay exactly as they were.
# Returns True if the file was changed.
BROKEN_VERSION_LINE = re.compile(rb"^([ \t]*)VERSION\](?=[ \t]*(\r\n|\r|\n|$))")

def fix_version_section(file_to_read):
    try:
        with open(file_to_read, "rb") as f:
            lines = f.read().splitlines(keepends=True)
    except OSError:
        return False

    changed = False
    for i, line in enumerate(lines):
        new_line, count = BROKEN_VERSION_LINE.subn(rb"\1[VERSION]", line, count=1)
        if count:
            lines[i] = new_line
            changed = True
            if verbose: print("  Fixed 'VERSION]' -> '[VERSION]' on line " + str(i + 1) + " of " + file_to_read)

    if changed:
        try:
            with open(file_to_read, "wb") as f:
                f.writelines(lines)
            fixed_files.append(file_to_read)
        except OSError as err:
            print("Could not write fix to " + file_to_read + ": " + str(err))
            return False
    return changed

# Reads all the aircraft.cfg files from the directory models_directory.
# Assemble all the aircraft.cfg entries into a dictionary with format: model_list[CallsignPrefix][TypeCode][ModelName]
def create_model_list():
    model_list = defaultdict(dict)

    for model in os.listdir(models_directory):
        global model_list_len
        model_list_len = model_list_len + 1
        file_to_read = models_directory + "/" + model + "/aircraft.cfg"
        # strict=False: some MTL aircraft.cfg files contain a section or option twice (for example a second
        # [VERSION] section at the end of the file). The default strict parser would refuse the whole file.
        config = configparser.ConfigParser(strict=False)
        try:
            if verbose: print("Reading " + file_to_read + "...")
            fix_version_section(file_to_read)
            # MTL files are UTF-8 (sometimes with a BOM); a few older ones use a Windows code page instead.
            # Try UTF-8 first and fall back to cp1252, independent of the locale the script runs under.
            try:
                config.read(file_to_read, encoding="utf-8-sig")
            except UnicodeDecodeError:
                config = configparser.ConfigParser(strict=False)
                config.read(file_to_read, encoding="cp1252")
        except configparser.Error as err:
            print(err)
            errored_files.append(file_to_read)
            pass
        except UnicodeDecodeError as err:
            print("Could not decode " + file_to_read + ": " + str(err))
            errored_files.append(file_to_read)
            pass
        for section in config.sections():
            if "fltsim" in section:
                global texture_len
                texture_len = texture_len + 1
                try:
                    acf_type = determine_aircraft_type(config, section)
                except Exception as err:
                    print(file_to_read + " [" + section + "] has no readable aircraft type (" + str(err) + "), skipping.")
                    errored_files.append(file_to_read)
                    continue

                # TypeCode cannot be blank.
                if acf_type == "":
                    print(file_to_read + " [" + section + "] has an empty aircraft type, skipping.")
                    errored_files.append(file_to_read)
                    continue

                try:
                    texture_title = config[section]["title"]
                    if "\"" in texture_title: texture_title = texture_title[1:-1].encode('utf-8')
                    global lib
                    if lib == "ivao": texture_title = texture_title.decode('utf-8')
                    callsign_prefix = determine_callsign_prefix(config[section])
                    texture_name = config[section].get("texture", "")
                    ui_variation = config[section].get("ui_variation", "")
                except Exception as err:
                    print(file_to_read + " [" + section + "] could not be read (" + str(err) + "), skipping.")
                    errored_files.append(file_to_read)
                    continue
                if lib == "ivao":
                    standard = is_standard_livery(texture_name, ui_variation)
                    livery_info[texture_title] = (callsign_prefix, acf_type, texture_name.strip("\""), ui_variation.strip("\""), standard)
                    if not standard:
                        special_titles.add(texture_title)
                        if verbose: print("  Special livery: " + texture_title + " (" + ui_variation.strip("\"") + ")")
                try:
                    model_list[callsign_prefix][acf_type].append(texture_title)
                except:
                    model_list[callsign_prefix][acf_type] = [texture_title]

    return model_list

# Goes through the models_list and writes the rules to the output file.
# Some airlines have multiple available textures for a single type. These are combined into one entry and the ModelNames are separated with "//"
# With standard_only, the special liveries are left out (see is_standard_livery).
def write_rules(model_list, output, standard_only):
    for airline in model_list:
        global airlines_len
        if not standard_only: airlines_len = airlines_len + 1

        for type in model_list[airline]:
            variants = model_list[airline][type]
            if standard_only:
                # Keep only the standard liveries. If an airline has nothing but special liveries for this type,
                # keep them all: a special livery is still a better match than a generic aircraft.
                standard_variants = [v for v in variants if v not in special_titles]
                global special_skipped, special_kept
                if len(standard_variants) > 0:
                    special_skipped += len(variants) - len(standard_variants)
                    variants = standard_variants
                else:
                    special_kept += len(variants)
                    for v in variants: kept_titles.add(v)
            variant_string = ""
            for variant in variants:
                if "&" in variant: continue
                variant_string += variant
                if variant != variants[-1]:
                    variant_string += "//"
            
            if(type.endswith("\"")):
                type = type[:-1]
            output.write(build_rule(airline, type, variant_string))
            if verbose and not standard_only: print("Created rule for airline " + airline + " type " + type)
            global rules_len
            if not standard_only: rules_len = rules_len + 1

# Writes one VMR file.
def write_vmr(model_list, path, standard_only):
    output = open(path, "w")
    output.write("<?xml version=\"1.0\" encoding=\"utf-8\"?> \n")
    output.write("<ModelMatchRuleSet> \n")
    write_rules(model_list, output, standard_only)
    output.write("</ModelMatchRuleSet> \n")
    output.write("<!-- VMR created by create-ivao-vmr https://github.com/andrewward2001/create-ivao-vmr -->")
    output.close()

# Writes a CSV with every livery, its name from the catalog and whether the standard-only VMR treats it as standard,
# special, or special-but-kept (the airline has no standard livery for that type).
def write_livery_list(path):
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write("mtlid;airline;type;texture;name;livery\n")
        for title in sorted(livery_info, key=lambda t: (livery_info[t][0], livery_info[t][1], t)):
            airline, acf_type, texture, name, standard = livery_info[title]
            if standard: kind = "standard"
            elif title in kept_titles: kind = "special (kept, no standard livery)"
            else: kind = "special"
            f.write(";".join([title, airline, acf_type, texture, name.replace(";", ","), kind]) + "\n")

def main():
    print("Building VMR for library: " + lib)
    print("Reading models from: " + os.path.abspath(models_directory))
    if not os.path.isdir(models_directory):
        print("ERROR: the directory " + models_directory + " does not exist.")
        print("Run this script from the root folder of the MTL library (the folder that contains \"SimObjects\"), or pass the path with -d.")
        return

    # Collect the rules first, so that a crash while reading the models never leaves a half-written VMR behind.
    model_list = create_model_list()

    output_directory.mkdir(parents=True, exist_ok=True)
    write_vmr(model_list, output_directory / output_file, False)
    if lib == "ivao":
        stem = Path(output_file).stem
        standard_file = stem + "_standard" + Path(output_file).suffix
        livery_list_file = stem + "_liveries.csv"
        write_vmr(model_list, output_directory / standard_file, True)
    print("\n\nDone!")
    print("Processed: " + str(model_list_len) + " models.")
    print("Processed: " + str(texture_len) + " textures.")
    print("Processed: " + str(airlines_len) + " airlines.")
    print("Processed: " + str(rules_len) + " rules.")
    print("VMR created: " + os.path.abspath(output_directory / output_file))
    if lib == "ivao":
        print("Standard liveries only VMR created: " + os.path.abspath(output_directory / standard_file))
        print("  Special liveries left out: " + str(special_skipped) + ".")
        if special_kept > 0:
            print("  Special liveries kept because the airline has no standard livery for that aircraft type: " + str(special_kept) + ".")
        try:
            write_livery_list(output_directory / livery_list_file)
            print("Livery list created: " + os.path.abspath(output_directory / livery_list_file))
        except OSError as err:
            print("Could not write the livery list " + livery_list_file + ": " + str(err))
    if(len(fixed_files) != 0):
        print("\n\nSome aircraft.cfg files had a broken \"VERSION]\" section header. It was fixed to \"[VERSION]\" so the file could be read:")
        for file in fixed_files:
            print(file)
    if(len(errored_files) != 0):
        print("\n\nSome files had errors and were not included in the VMR:")
        for file in sorted(set(errored_files)):
            print(file)
        print("Usually this is because of an error where the file says [VERSION]. See GitHub for more details.")
        print("The VMR was still created but aircraft of this type will not show up unless the problem is fixed and the script is run again.")

if __name__ == "__main__":
    parse_command_line()
    try:
        main()
    except Exception:
        print("\n\nERROR: the script crashed. Details:")
        traceback.print_exc()
        print("The full output was saved to " + os.path.abspath(log_file) + ". Please attach it when reporting the problem on GitHub.")
    finally:
        if pause_at_end:
            try:
                input("\nPress Enter to close this window...")
            except EOFError:
                pass
