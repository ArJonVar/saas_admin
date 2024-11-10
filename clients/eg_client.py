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
        self.egnyte_token = egnyte_token
        self.eg_user_list = self.recusively_generate_eg_user_list(1, [])

    #region helper funcs
    def return_dict_from_api_resp(self, resp:requests.models.Response, variable_name:str) -> dict:
        '''takes in egnyte API responses and does standard debug log and converting to dict to avoid errrors'''
        # Parse JSON content into a dictionary
        resp_dict = json.loads(resp.content.decode('utf-8'))

        # Log the pretty-printed dictionary
        logger.debug(f"{variable_name}: {json.dumps(resp_dict, indent=4)}")

        # Return the dictionary
        return resp_dict
    #endregion
    def generate_eg_project_path(self, project: ProjectObj):
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
        
        return self.return_dict_from_api_resp(folder_api_resp, 'folder_api_dict')
    def set_permissions_on_new_folder(self, project:ProjectObj) -> requests.models.Response:
        '''creates the permission set that we use for projects (w state level, project level, and project-folder level)
        for some reason this api call does not have a .content responce fyi'''
        url = f"https://dowbuilt.egnyte.com/pubapi/v2/perms/{project.eg_path}"
        headers = CaseInsensitiveDict()
        headers["Authorization"] = f"Bearer {egnyte_token}"
        headers["Content-Type"] = "application/json"
        if project.state != "CA":
            state = project.state
        elif project.region == "NORCAL":
            state = 'NorCal'
        elif project.region == "SOCAL":
            state = 'SoCal'
        elif project.state == "CA":
            # rare case that the state is Ca but the reigon is not norcal/socal
            state = 'NorCal'
        
        special_proj_add= ', "Special Projects Admin": "Editor"'
        data = '{"groupPerms":{"' + f"{project.name}_{project.enum}" + '":"Full", "State_' + state + '":"Editor", "Projects": "Editor"'+ f'{special_proj_add if project.job_type == "Special Projects" or project.job_type == "Small Projects" else ""}'+'}}'
        logger.debug(f"permissions setting: {data}")

        folder_permission_api_resp = requests.post(url, headers=headers, data=data)

        return folder_permission_api_resp 
    def copy_folders_to_new_location(self, source_path:str, destination_path:str) -> dict:
        '''copies folder(s) from source to destination, inherenting permissions of destination'''
        url = f"https://dowbuilt.egnyte.com/pubapi/v1/fs/{source_path}"

        headers = CaseInsensitiveDict()
        headers["Authorization"] = f"Bearer {egnyte_token}"
        headers["Content-Type"] = "application/json"

        data = '{"action":"copy", "destination":"' + destination_path + '", "permissions": "inherit_from_parent"}'

        folder_move_api_resp = requests.post(url, headers=headers, data=data)
        folder_move_api_dict =  {json.dumps(json.loads(folder_move_api_resp.content.decode('utf-8')), indent=4)}
        logger.debug(f'folder move api dict: {folder_move_api_dict}')
        return self.return_dict_from_api_resp(folder_move_api_resp, 'folder_move_api_dict')
    def restrict_move_n_delete(self, path:str) -> dict:
        '''changes default setting so full owners cannot move/delete root folder, just folders inside'''
        url = f"https://dowbuilt.egnyte.com/pubapi/v1/fs/{path}"

        headers = CaseInsensitiveDict()
        headers["Authorization"] = f"Bearer {egnyte_token}"
        headers["Content-Type"] = "application/json"        

        data = '{"restrict_move_delete": "true"}'       

        restriction_api_resp= requests.patch(url, headers=headers, data=data)
        return self.return_dict_from_api_resp(restriction_api_resp, 'restriction_api_dict')
    def generate_folder_link(self, path, posting_data:PostingData) -> PostingData:
        '''gets folder, finds id, and then returns ProjectObj with the new link'''
        url = f"https://dowbuilt.egnyte.com/pubapi/v1/fs/{path}"

        headers = CaseInsensitiveDict()
        headers["Authorization"] = f"Bearer {egnyte_token}"


        get_folder_api_resp = requests.get(url, headers=headers)
        get_folder_api_dict = self.return_dict_from_api_resp(get_folder_api_resp, 'get_folder_api_dict')
        id = get_folder_api_dict.get("folder_id")
        posting_data.eg_link  = 'https://dowbuilt.egnyte.com/navigate/folder/' + id    
        return posting_data
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
        headers["Authorization"] = f"Bearer {egnyte_token}"

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

        time.sleep(5)

        new_permissions_group_api_resp = requests.post(url, headers=headers, data=data)
        new_permissions_group_api_dict = self.return_dict_from_api_resp(new_permissions_group_api_resp, 'new_permissions_group_api_dict')
        permission_group_id = new_permissions_group_api_dict.get("id")
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