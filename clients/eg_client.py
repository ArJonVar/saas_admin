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
from clients.ss_client import SmartsheetClient, ProjectObj, PostingData
from dataclasses import dataclass
import logging
from configs.setup_logger import setup_logger
logger = setup_logger(__name__, level=logging.DEBUG)

# Check if we are on a dev computer or server
if os.name == 'nt':
    sys.path.append(r"Z:\Shared\IT\Projects and Solutions\Python\Ariel\_Master")
else:
    sys.path.append(os.path.expanduser(r"~/_Master"))

# Import master_logger, master_smartsheet_grid, and master_globals
try:
    from master_globals import egnyte_token
except ImportError as e:
    print(f"Error importing module: {e}")
    sys.exit(1)
#endregion

#region Models
@dataclass
class Person():
    name: str
#endregion

# testing git CHANGED ANOTHER TIME
class EgnyteClient():
    '''words'''
    def __init__(self):
        logger.debug('Initializing Egnyte Client...')
        self.eg_link = ""
        self.eg_user_list = self.recusively_generate_eg_user_list(1, [])

    #region helper funcs
    #endregion
    def update_eg_project_path(self, project: ProjectObj):
        '''there is default path in projects folder + few outliers'''
        if project.state != "CA":
            project.eg_path = f"Shared/Projects/{project.state}/{project.name}_{project.enum}"
        elif project.region == "NORCAL":
            project.eg_path = f"Shared/Projects/NorCal/{project.name}_{project.enum}"
        elif project.region == "SOCAL":
            project.eg_path = f"Shared/Projects/SoCal/{project.name}_{project.enum}"  
        elif project.state == "CA":
            project.eg_path = f"Shared/Projects/NorCal/{project.name}_{project.enum}"

    #region folders
    def create_folder(self, path:str) -> dict:
        '''uses api to create folder'''
        url=f'https://dowbuilt.egnyte.com/pubapi/v1/fs/{path}'
        
        headers = CaseInsensitiveDict()
        headers["Authorization"] = f"Bearer {egnyte_token}"
        headers["Content-Type"] = "application/json"

        data = '{"action":"add_folder"}'
        
        folder_api_resp = requests.post(url, headers=headers, data=data)
        folder_dict = json.dumps(json.loads(folder_api_resp.content.decode('utf-8')), indent=4)
        
        logger.debug(f"create_folder inputs: URL:{url} HEADERS:{headers}, DATA:{data}")
        logger.debug(f"create_folder outputs: {folder_dict}")
        return folder_dict
    
    #endregion
    #region permissions roups
    def eg_user_list_api_call(self, index:int, eg_user_list:list) -> bool:
        """
        Makes an API call to the Egnyte user list endpoint to fetch user data.

        This function fetches up to 100 user records starting from the specified index
        and appends them to the provided `eg_user_list`. If no more users are found, 
        the function returns `False` to signal that recursion should stop.

        Args:
            index (int): The starting index for the API call.
            eg_user_list (list): A list to store user dictionaries containing 'name', 'email', and 'id'.

        Returns:
            bool: 
                - `True` if more users are available for fetching.
                - `False` if no more users are available, indicating the end of the data.
        """
        recursion_bool = True

        url = f"https://dowbuilt.egnyte.com/pubapi/v2/users?count=100&startIndex={index}"
        headers = CaseInsensitiveDict()
        headers["Authorization"] = f"Bearer {self.egnyte_token}"

        resp = requests.get(url, headers=headers)
        resp_dict = json.loads(resp.content.decode("utf-8"))
        information_pretty = json.dumps(resp_dict, indent=4)
        information_dict = json.loads(information_pretty)

        for user in information_dict.get("resources"):
            name = user.get("name"). get("formatted")
            user_id = user.get("id")
            email = user.get("email")
            eg_user_dict = {"name": name, "email": email, "id": user_id}
            eg_user_list.append(eg_user_dict)
        if len(information_dict.get("resources")) == 0:
            recursion_bool = False

        return recursion_bool
    def recusively_generate_eg_user_list(self, index:int, eg_user_list:list) ->list:
        """
        Recursively retrieves all user data from the Egnyte API and returns the complete user list. 

        This function calls `eg_user_list_api_call` to fetch user data in batches of 100.
        It continues making API calls with incremented indices until all user data is retrieved.    

        Args:
            index (int): The starting index for the initial API call. Typically `0`.
            eg_user_list (list): A list to store user dictionaries. Should be empty initially.  

        Returns:
            list: A list of dictionaries where each dictionary contains:
                - 'name': The formatted name of the user.
                - 'email': The email address of the user.
                - 'id': The unique ID of the user.
        """
        recursion_bool = self.eg_user_list_api_call(index, eg_user_list)
        if recursion_bool == True:
            new_index = int(index) + 100
            self.recusively_generate_eg_user_list(new_index, eg_user_list)

        return eg_user_list
    def prepare_new_permission_group(self, project:ProjectObj) -> list:
        '''looks up user emails and maps to egnyte user values so future api calls can be done simply'''
        permission_members = []
        for employee in project.user_emails:
            if employee == "none":
                pass
            else:
                for user in self.eg_user_list:
                    if employee == user.get("email"):
                        permission_members.append({"value":user.get("id")})
        if permission_members == []:
            # to make it never empty, the group adds me (ariel) if no one else...
            permission_members.append({"value":309})
        logger.debug(f"debug prepare permissions: {permission_members}")
        return permission_members
    def generate_permission_group(self, permission_members:list, project:ProjectObj) -> int:
        url = "https://dowbuilt.egnyte.com/pubapi/v2/groups"

        headers = CaseInsensitiveDict()
        headers["Authorization"] = f"Bearer {egnyte_token}"
        headers["Content-Type"] = "application/json"

        logger.debug(f"permission_members: {permission_members}")

        if len(permission_members) == 0:
            data_raw='{"displayName":"' + project.name+"_"+project.enum + '}'
            data = re.sub("\'", '"', data_raw)
        else:
            data_raw = '{"displayName":"' +  project.name+"_"+project.enum +'", "members":' + str(permission_members) + '}'
            data = re.sub("\'", '"', data_raw)

        logger.debug(f"data: {data}")
        time.sleep(5)
        new_permissions_group_api_resp = requests.post(url, headers=headers, data=data)
        logger.debug(f"permission group api response: {new_permissions_group_api_resp}")

        new_permissions_group_dict = json.dumps(json.loads(new_permissions_group_api_resp.decode('utf-8')), indent=4)
        logger.debug(f"api response ad dict: {new_permissions_group_dict }")

        permission_group_id = new_permissions_group_dict.get("id")
        logger.debug(f"list of permission ids: {permission_group_id}")

        return permission_group_id
    #endregion
    def id_from_url(self):
        '''takes a url such as X and generates the ID such as Y'''
        input = self.proj_dict.get("eg_link")
        split = re.split('https://dowbuilt.egnyte.com/navigate/folder/', input)
        self.folder_id=split[1]
    
    def path_from_id(self):
        '''takes the url like X and generates a path like Y'''
        url = f"https://dowbuilt.egnyte.com/pubapi/v1/fs/ids/folder/{self.folder_id}"
        headers = CaseInsensitiveDict()
        headers["Authorization"] = f"Bearer {egnyte_token}"
        resp = requests.get(url, headers=headers)
        resp_dict = json.loads(resp.content.decode("utf-8"))
        folder_information_pretty = json.dumps(resp_dict, indent=4)
        folder_information_dict = json.loads(folder_information_pretty)
        project.eg_path_from_id = folder_information_dict.get("path")

if __name__ == "__main__":
    pass