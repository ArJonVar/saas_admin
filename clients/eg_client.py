#region imports and variables
import os
import sys
import smartsheet
import time
from datetime import datetime
from smartsheet.exceptions import ApiError
import requests
from requests.structures import CaseInsensitiveDict
import json
import re
import pandas as pd
from logger import ghetto_logger
from V3.archive.globals import egnyte_token, smartsheet_token
from dataclasses import dataclass

# Check if we are on a dev computer or server
if os.name == 'nt':
    sys.path.append(r"Z:\Shared\IT\Projects and Solutions\Python\Ariel\_Master")
else:
    sys.path.append(os.path.expanduser(r"~/_Master"))

# Import master_logger, master_smartsheet_grid, and master_globals
try:
    from master_logger import ghetto_logger
    from master_smartsheet_grid import grid
    from master_globals import sensative_egnyte_token
except ImportError as e:
    print(f"Error importing module: {e}")
    sys.exit(1)
#endregion

#region Models
@dataclass
class Person():
    name: str
#endregion

# testing git DIFFERENT CHANGE
class EgnyteClient():
    '''words'''
    def __init__(self, config):
        self.log=ghetto_logger("eg_client.py")
        self.apply_config(config)
        self.eg_link = ""

    def apply_config(self, config):
        '''turns all config items into self.key = value'''
        for key, value in config.items():
            setattr(self, key, value)


    def id_from_url(self):
        '''takes a url such as X and generates the ID such as Y'''
        input = self.proj_dict.get("eg_link")
        split = re.split('https://dowbuilt.egnyte.com/navigate/folder/', input)
        self.folder_id=split[1]
    
    def path_from_id(self):
        '''takes the url like X and generates a path like Y'''
        url = f"https://dowbuilt.egnyte.com/pubapi/v1/fs/ids/folder/{self.folder_id}"
        headers = CaseInsensitiveDict()
        headers["Authorization"] = f"Bearer {self.egnyte_token}"
        resp = requests.get(url, headers=headers)
        resp_dict = json.loads(resp.content.decode("utf-8"))
        folder_information_pretty = json.dumps(resp_dict, indent=4)
        folder_information_dict = json.loads(folder_information_pretty)
        self.path_from_id = folder_information_dict.get("path")

if __name__ == "__main__":
    config = {
        'egnyte_token':sensative_egnyte_token,
        # group ids (that need to be part of all projects)
        'field_admins_id':  2077914675079044,
        'project_admins_id': 2231803353294724,
        'project_review_id': 1394789389232004,
        'pythscript_checkbox_column_id': 1907059135932292
    }
    eg = EgnyteClient(config)