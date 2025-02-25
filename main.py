import clr
import time
import json
import sys
import os
import subprocess
import xml.etree.ElementTree as ET
from slpp import slpp as lua

# Attempt to open the JSON file and load data
with open("app.config", "r") as file:
    data = json.load(file)
                
json_config_data = data
DEBUG = data.get("DEBUG", "False")
# Access specific values from the JSON data
#vistaDB_DLL = data.get("vistaDB_DLL", "")

class title():
    def __init__(self):
        self.titleID = None
        self.LongName = None
        self.SortName = None
        self.DiskSN = None
        self.ProductType = None

#-------------------------------IMPORT DLL(s)-------------------------------------------
clr.AddReference(data.get("redboxHALClientDLL", "C:\\Program Files\\Redbox\\REDS\\Kiosk Engine\\bin\\Redbox.HAL.Client"))
clr.AddReference(data.get("redboxIPCFrameworkDLL", "C:\\Program Files\\Redbox\\REDS\\Kiosk Engine\\bin\\Redbox.IPC.Framework"))
from Redbox.HAL.Client import HardwareService, HardwareJobSchedule, HardwareJob
from Redbox.IPC.Framework import IPCProtocol

clr.AddReference(data.get("productLookupCatalog", "C:\\Program Files\\Redbox\\REDS\\Kiosk Engine\\bin\\Redbox.ProductLookupCatalog"))
from Redbox.ProductLookupCatalog import Archive
        

clr.AddReference(data.get("VistaDB", "C:\\Program Files\\Redbox\\REDS\\Kiosk Engine\\bin\\VistaDB.NET20"))
# Import the VistaDB namespaces
from VistaDB.Provider import VistaDBConnection
#-------------------------------IMPORT DLL(s)-------------------------------------------

connection = HardwareService(IPCProtocol.Parse(data.get("HAL_URL", "rcp://127.0.0.1:7001")))

schedule = HardwareJobSchedule()
job = HardwareJob(connection)
#----------------------------------------------------------------------------
#                       NOTES FOR Getting SNs
#       1. Read the XML ignoring the empties and Unknowns
#       2. Going through each item barcode in the list, use the DLL to convert to title ID and Long Name, if not found note as UNKNOWN in both lists
#       3. Loop through the title ID list, and check if each exists in the Keep list, if not then append, if it does already exist, then add the same index position of SN list to remove list
#       4. Also add the long name to the remove_longname list
#       5. Once complete, list is done and ready for binning!
#
#----------------------------------------------------------------------------
def search(serialNumber):
    # Get the text from the input line
    search_input = serialNumber

    connection = Archive(data.get("inventory", "C:\\Program Files\\Redbox\\REDS\\Kiosk Engine\\data\\inventory.data"), True)
    try:
        debug("Checking SN: ", search_input)
        inventory = connection.Find(str(search_input))
        titleIDResult = inventory.get_TitleId()
        debug("Title ID: ", titleIDResult)
    except AttributeError:
        print("SN does not exist in the Database: ", search_input)
        titleIDResult = 'UNKNOWN'

    finally:
        connection.Dispose()

    getQuery = "SELECT * FROM ProductCatalog WHERE [Key] = " + str(titleIDResult)

    try:
        connection_string = data.get("profile", "Data Source=C:\\Program Files\\Redbox\\REDS\\Kiosk Engine\\data\\profile.data")
        connection = VistaDBConnection(connection_string)
        # Open the database connection
        connection.Open()
        command = connection.CreateCommand()
        command.CommandText = getQuery
    
        # Execute the query and read the results
        reader = command.ExecuteReader()
    
        # Read each row in the result and convert to JSON and append to a list
        while reader.Read():
            # Fetch the value of the 'Value' column
            value_string = str(reader["Value"])
            #decode LUA to JSON
            value_str_json = lua.decode(value_string)

        if reader:
            reader.Close()
        sortName = value_str_json['sort_name']
    except Exception as e:
        # Print any errors that occur
        sortName = 'UNKNOWN'
        print(f"Error: {e}")
        return titleIDResult,sortName

    finally:
        # Clean up resources
        if connection.State == 'Open':
            connection.Close()

    return value_str_json

def extract_nonempty_ids(xml_file):
    tree = ET.parse(xml_file)
    root = tree.getroot()
    
    ids = [item.get('id') for item in root.findall('item') if item.get('id') != "EMPTY"]
    #[item.get('id') for item in root.findall('item') if item.get('id') not in {"EMPTY", "UNKNOWN"}]

    return ids

#Get the list of Jobs currently in the HAL
def GetAllJobs(connect):
    try:
        arraylist = []
        result, jobss = connect.GetJobs()
        num = 0
        for x in jobss:
            arraylist.append(x.ToString())
            num = num+1
    except Exception as e:
        print(f"Error: {e}")
    return arraylist

def binDisks(connect,diskSNtoBin,schedule,job):
    try:
        id = connect.LoadBin(diskSNtoBin,schedule,job)
    except Exception as e:
        print(f"Error: {e}")
    
def getDifference(list1, list2):
    difference = list(set(list2) - set(list1))
    return difference[0]

def getSchedulerStatus(connect):
    try:
        status = ""
        result = connect.GetSchedulerStatus(status)
    except Exception as e:
        print(f"Error: {e}")
    return result

def trashJob(connect,jobID):
    try:
        result = connect.TrashJob(jobID)
    except Exception as e:
        print(f"Error: {e}")
    return result

def waitForIdle(connect, interval=5, timeout=3600):
    """
    Runs a Python function every few seconds until it returns a good response or times out.

    :param command_function: A function that returns a value to be checked.
    :param check_function: A function that evaluates the response and returns True if it's good.
    :param interval: Time in seconds to wait before retrying.
    :param timeout: Maximum time in seconds before giving up (default: 1 hour).
    """
    start_time = time.time()  # Record start time
    time.sleep(interval)  # Wait before retrying

    while True:
        result = getSchedulerStatus(connect)  # Call the function
        debug("result: ", result[1])
        if result[1] == 'idle':  # Check if response is good
            print("Job Complete! Continuing...")
            break  # Exit loop if response is good

        elapsed_time = time.time() - start_time  # Calculate elapsed time
        if elapsed_time >= timeout:
            print("Timeout reached! Stopping after", timeout, "seconds.")
            return False  # Return False to indicate failure (or raise an exception)

        print("Job in progress, re-checking in", interval, "seconds...")
        time.sleep(interval)  # Wait before retrying
    
    return True  # Return True if successful

def getInventory(executable):
    try:
        result = subprocess.run([executable, "-dumpInventory"], capture_output=True, text=True)
    except Exception as e:
        print(f"Error: {e}")
    return result.returncode

def debug(*args, **kwargs):
    if DEBUG:
        print("[DEBUG]:", *args, **kwargs)


titleList = []
title_id = []
long_namg = []
diskSN = []

keep_List = []
remove_List = []
remove_ListName = []

beginJobs = []
endJobs = []

print("Welcome to the Kiosk Duplicate Binning Script, V0.1")
print("By: Zach3697")
print("")
print("This script currently treats each type as a seperate title")
print("and will keep a DVD, Blu-Ray, and 4K copy of each title.")
print("A fututre version will address this soon and can be run")
print("after this script has been used.")
print("--------------------------------------------------------------")
print("")
print("Please select from the options below:")
print("1. Just get stats on the nuber of duplicates in my kiosk (no binning)")
print("2. Start the process of removing duplicates!")
print("")
user_choice = input("Enter your choice (1-2): ")

print("Please Wait.....")

getInventory(data.get("HALUtilities", "HalUtilities.exe"))

non_empty_ids = extract_nonempty_ids(data.get("XML", "inventory.xml"))

for id in non_empty_ids:
    if id != "UNKNOWN":
        titleInfo = search(id)
        record = title()
        record.DiskSN = id
        record.LongName = titleInfo['long_name']
        record.ProductType = titleInfo['product_type_id']
        record.SortName = titleInfo['sort_name']
        record.titleID = titleInfo['product_id']
        if record.titleID != 1139:
            titleList.append(record)
 
for index,title in enumerate(titleList):
    debug("Title: ", title.LongName)
    if title.titleID in keep_List:
        remove_List.append(title.DiskSN)
        remove_ListName.append(title.LongName)
    else:
        keep_List.append(title.titleID)

print("Removing these titles: ", remove_ListName)
print("Which associates to these SNs: ", remove_List)
print("")
user_choice = input("Do you wish to remove these duplicates? (Y/N): ")



if user_choice == "2" or user_choice == "Y" or user_choice == "y":
    beginJobs = GetAllJobs(connection)

    binDisks(connection,remove_List,schedule,job)

    endJobs = GetAllJobs(connection)

    job.ID = getDifference(beginJobs,endJobs)
    job.SetLabel("Remove Duplicates Disk(s)")
    job.Pend()

    binResult = waitForIdle(connection,5,3600)

    if binResult:
        print("Duplicates Removed!")
        trashJob(connection, job.ID)

    else:
        print("Bin Job Timeout! Please check HAL Management Console for JOB ID: ")
        print(job.ID)

