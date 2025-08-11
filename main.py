import clr
import time
import json
import sys
import os
import subprocess
import xml.etree.ElementTree as ET
from slpp import slpp as lua
from collections import defaultdict

# Attempt to open the JSON file and load data
with open("app.config", "r") as file:
    data = json.load(file)

json_config_data = data

# Make DEBUG a true boolean
DEBUG = data.get("DEBUG", False)
if isinstance(DEBUG, str):
    DEBUG = DEBUG.lower() == "true"

class title():
    def __init__(self):
        self.titleID = None
        self.LongName = None
        self.SortName = None
        self.DiscSN = None
        self.ProductType = None

#-------------------------------IMPORT DLL(s)-------------------------------------------
clr.AddReference(data.get("redboxHALClientDLL", "C:\\Program Files\\Redbox\\REDS\\Kiosk Engine\\bin\\Redbox.HAL.Client"))
clr.AddReference(data.get("redboxIPCFrameworkDLL", "C:\\Program Files\\Redbox\\REDS\\Kiosk Engine\\bin\\Redbox.IPC.Framework"))
from Redbox.HAL.Client import HardwareService, HardwareJobSchedule, HardwareJob
from Redbox.IPC.Framework import IPCProtocol

clr.AddReference(data.get("productLookupCatalog", "C:\\Program Files\\Redbox\\REDS\\Kiosk Engine\\bin\\Redbox.ProductLookupCatalog"))
from Redbox.ProductLookupCatalog import Archive

clr.AddReference("System.Collections")
from System.Collections.Generic import Stack

clr.AddReference(data.get("VistaDB", "C:\\Program Files\\Redbox\\REDS\\Kiosk Engine\\bin\\VistaDB.NET20"))
from VistaDB.Provider import VistaDBConnection
#-------------------------------IMPORT DLL(s)-------------------------------------------

connection = HardwareService(IPCProtocol.Parse(data.get("HAL_URL", "rcp://127.0.0.1:7001")))
schedule = HardwareJobSchedule()
job = HardwareJob(connection)

#----------------------------------------------------------------------------
#                       NOTES FOR Seperating by type
#       Convert each SN to title ID, then search the product group table for that title id and store the group name/ID in the title class
#       Create a class for groups where you have grroup ID, Name, DVD Title#, Bluray Title#, and 4K Title #.
#       Go through the title list and apply each unique group ID to the class along with the name
#
#
#
#
#
#----------------------------------------------------------------------------
def search(serialNumber):
    connection_catalog = Archive(
        data.get("inventory", r"C:\Program Files\Redbox\REDS\Kiosk Engine\data\inventory.data"),
        True
    )
    try:
        debug("Checking SN:", serialNumber)
        inventory = connection_catalog.Find(str(serialNumber))
        titleID = inventory.get_TitleId()
        debug("Title ID:", titleID)
    except AttributeError:
        print(f"SN does not exist in the Database: {serialNumber} — skipping.")
        return {
            "long_name":       "UNKNOWN",
            "sort_name":       "UNKNOWN",
            "product_type_id": "UNKNOWN",
            "product_id":      "UNKNOWN"
        }
    finally:
        try:
            connection_catalog.Dispose()
        except Exception:
            pass

    getQuery = f"SELECT * FROM ProductCatalog WHERE [Key] = {titleID}"

    try:
        conn_str = data.get(
            "profile",
            "Data Source=C:\\Program Files\\Redbox\\REDS\\Kiosk Engine\\data\\profile.data"
        )
        conn = VistaDBConnection(conn_str)
        conn.Open()

        cmd = conn.CreateCommand()
        cmd.CommandText = getQuery
        reader = cmd.ExecuteReader()

        value_str_json = None
        if reader.Read():
            lua_blob = str(reader["Value"])
            value_str_json = lua.decode(lua_blob)

        reader.Close()

        if not value_str_json:
            raise ValueError("No catalog data for TitleID " + str(titleID))

    except Exception as e:
        print(f"Error querying ProductCatalog: {e}")
        return {
            "long_name":       "UNKNOWN",
            "sort_name":       "UNKNOWN",
            "product_type_id": "UNKNOWN",
            "product_id":      titleID
        }
    finally:
        try:
            if getattr(conn, "State", None) == "Open":
                conn.Close()
        except Exception:
            pass

    return {
        "long_name":       value_str_json.get("long_name",       "UNKNOWN"),
        "sort_name":       value_str_json.get("sort_name",       "UNKNOWN"),
        "product_type_id": value_str_json.get("product_type_id", "UNKNOWN"),
        "product_id":      value_str_json.get("product_id",      titleID),
    }

def extract_nonempty_ids(xml_file):
    tree = ET.parse(xml_file)
    root = tree.getroot()
    return [item.get('id') for item in root.findall('item') if item.get('id') != "EMPTY"]

def GetAllJobs(connect):
    try:
        arraylist = []
        result, jobss = connect.GetJobs()
        for x in jobss:
            arraylist.append(x.ToString())
    except Exception as e:
        print(f"Error: {e}")
    return arraylist

def binDiscs(connect, discSNtoBin, schedule, job):
    try:
        _ = connect.LoadBin(discSNtoBin, schedule, job)
    except Exception as e:
        print(f"Error: {e}")

def getDifference(list1, list2):
    diff = list(set(list2) - set(list1))
    return diff[0] if diff else None

def getSchedulerStatus(connect):
    try:
        status = ""
        result = connect.GetSchedulerStatus(status)
    except Exception as e:
        print(f"Error: {e}")
        result = (False, "unknown")
    return result

def trashJob(connect, jobID):
    if not jobID:
        return False
    try:
        return connect.TrashJob(jobID)
    except Exception as e:
        print(f"Error: {e}")
        return False
        
def waitForIdle(connect, interval=5, timeout=3600):
    start_time = time.time()
    """
    start_time = time.time()
    Runs a Python function every few seconds until it returns a good response or times out.
    time.sleep(interval)
    :param command_function: A function that returns a value to be checked.
    :param check_function: A function that evaluates the response and returns True if it's good.
    :param interval: Time in seconds to wait before retrying.
    :param timeout: Maximum time in seconds before giving up (default: 1 hour).
    """
    time.sleep(interval)

    while True:
        result = getSchedulerStatus(connect)
        try:
            debug("result:", result[1])
            if result[1] == 'idle':
                break
        except Exception:
            pass

        if time.time() - start_time >= timeout:
            print(f"Timeout reached after {timeout} seconds.")
            return False

        print(f"Job in progress, re-checking in {interval} seconds...")
        time.sleep(interval)

    return True

def getInventory(executable):
    try:
        result = subprocess.run([executable, "-dumpInventory"], capture_output=True, text=True)
        return result.returncode
    except Exception as e:
        print(f"Error: {e}")
        return -1

def executeCommand(connect, job, command):
    try:
        return connect.ExecuteImmediate(command, job)
    except Exception as e:
        print(f"Error: {e}")
        return None

def scheduleJob(connect, schedule, job, command, priority):
    try:
        beginJobs = GetAllJobs(connect)
        _ = connect.ScheduleJob(command, "Schedule Job", False, schedule, job)
        endJobs = GetAllJobs(connect)

        job.ID = getDifference(beginJobs, endJobs)
        debug("Job ID:", job.ID)
        if job.ID:
            job.SetLabel("RDR Tool")
            job.Pend()
        return 1 if waitForIdle(connect, 1, 60) else 0
    except Exception as e:
        print(f"Error: {e}")
        return 0

def getDiscInBin(connect, schedule, job):
    scheduleJob(connect, schedule, job, "get-barcodes-in-bin", "Normal")
    snInBinResult = []
    stack = Stack[str]()
    _, stack = job.GetStack(stack)
    while stack.Count > 0:
        tempStore1 = stack.Pop()
        tempStore2 = tempStore1.split("|")
        snInBinResult.append(tempStore2[5])
    return snInBinResult

def print_duplicates_summary(names, sns, bin_count):
    if not sns:
        print("No duplicates to remove.")
        print(f"Total Number of Disc(s) in the bin: {bin_count}\n")
        return
    grouped = defaultdict(list)
    for name, sn in zip(names, sns):
        grouped[name].append(sn)

    print("Removing these duplicates:")
    for title, serials in grouped.items():
        print(f"{title} — {', '.join(serials)}")
    print(f"\nTotal Number of Duplicates to be removed: {len(sns)}")
    print(f"Total Number of Disc(s) in the bin: {bin_count}\n")

def startDuplicatesJob(connect, remove_List, schedule, job):
    beginJobs = GetAllJobs(connect)
    binDiscs(connect, remove_List, schedule, job)
    endJobs = GetAllJobs(connect)

    job.ID = getDifference(beginJobs, endJobs)
    debug("Job ID:", job.ID)
    if job.ID:
        job.SetLabel("RDR Tool: Remove Duplicates Disc(s)")
        job.Pend()

    if waitForIdle(connect, 5, 3600):
        print("Duplicates Removed!")
        trashJob(connect, job.ID)
        return 1
    else:
        print("Bin Job Timeout! Check HAL Management Console for JOB ID:", job.ID)
        return 0

def debug(*args, **kwargs):
    if DEBUG:
        print("[DEBUG]:", *args, **kwargs)

exit = "Y"
while exit.lower() == "y":
    titleList = []
    keep_List = []
    remove_List = []
    remove_ListName = []
    skipped_discs = []

    getInventory(data.get("HALUtilities", "HalUtilities.exe"))

    print("\nWelcome to the Kiosk Duplicate Binning Script, V0.1")
    print("By: Zach3697\n")
    print("This script currently treats each type as a separate title")
    print("and will keep a DVD, Blu-Ray, and 4K copy of each title.")
    print("--------------------------------------------------------------")
    print("1. Just get stats on the number of duplicates in my kiosk (no binning)")
    print("2. Start the process of removing duplicates!")
    print("3. Check which disc(s) are in the bin")
    print("4. Clear the Bin!\n")

    user_choice = input("Enter your choice (1-4): ")
    non_empty_ids = extract_nonempty_ids(data.get("XML", "inventory.xml"))
    binCount = len(getDiscInBin(connection, schedule, job))

    if user_choice in ("1", "2"):
        print("Please Wait.....")
        for id in non_empty_ids:
            if id == "UNKNOWN":
                continue
            titleInfo = search(id)
            if titleInfo['product_id'] == "UNKNOWN":
                skipped_discs.append(id)
                continue
            record = title()
            record.DiscSN = id
            record.LongName = titleInfo['long_name']
            record.ProductType = titleInfo['product_type_id']
            record.SortName = titleInfo['sort_name']
            record.titleID = titleInfo['product_id']
            if record.titleID != 1139:
                titleList.append(record)

        for t in titleList:
            if t.titleID in keep_List:
                remove_List.append(t.DiscSN)
                remove_ListName.append(t.LongName)
            else:
                keep_List.append(t.titleID)

        print_duplicates_summary(remove_ListName, remove_List, binCount)

        if skipped_discs:
            print(f"\nSkipped {len(skipped_discs)} unknown disc(s): {', '.join(skipped_discs)}\n")

        if len(remove_List) > 60 - binCount:
            print("Note: Bin does not have enough space for all discs.")
            remove_List = remove_List[0:60 - binCount]
        if remove_List and user_choice == "2":
            if input("Do you wish to remove these duplicates? (Y/N): ").lower() == "y":
                startDuplicatesJob(connection, remove_List, schedule, job)

    elif user_choice == "3":
        print("Checking Disc(s) in bin......")
        _ = scheduleJob(connection, schedule, job, "get-barcodes-in-bin", "Normal")
        stack = Stack[str]()
        _, stack = job.GetStack(stack)
        snInBinResult = []
        while stack.Count > 0:
            tempStore1 = stack.Pop()
            tempStore2 = tempStore1.split("|")
            snInBinResult.append(tempStore2[5])
        print(f"There are {len(snInBinResult)} disc(s) in the bin: {snInBinResult}")

    elif user_choice == "4":
        print("Resetting bin......")
        _ = executeCommand(connection, job, "DUMPBIN RESETCOUNTERMOVE")
        print("Bin Reset Complete!")

    else:
        print("Invalid selection")

    exit = input("Return to main menu? (Y/N): ")
