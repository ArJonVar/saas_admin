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

class EgnyteClient():
    '''words'''
    def __init__(self):
        logger.debug('Initializing Egnyte Client...')
        self.eg_link = ""
        self.egnyte_token = egnyte_token
        self.eg_user_list = self.recusively_generate_eg_user_list(1, [])
        self.cached_paths = {}

    #region helper funcs
    def return_dict_from_api_resp(self, resp:requests.models.Response, variable_name:str) -> dict:
        '''takes in egnyte API responses and does standard debug log and converting to dict to avoid errrors'''
        # Parse JSON content into a dictionary
        resp_dict = json.loads(resp.content.decode('utf-8'))

        # Log the pretty-printed dictionary
        logger.debug(f"{variable_name}: {json.dumps(resp_dict, indent=4)}")

        # Return the dictionary
        return resp_dict
    def handle_cached_paths(self, folder_id:str) -> str:
        '''checked for chached paths by folder id, otherwise loads it'''
        if self.cached_paths.get(folder_id) == None:
            self.cached_paths[folder_id] = self.get_folder_from_id(folder_id).get("path")
        return self.cached_paths.get(folder_id)
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
    def generate_id_from_url(self, project:ProjectObj) ->str:
        '''grabs folder id that is sitting in the direct links, returns false if the link is not direct link (and therefore split doesnt work)'''
        split = re.split('https://dowbuilt.egnyte.com/navigate/folder/', project.eg_link)
        try:
            folder_id = split[1]
        except IndexError:
            folder_id = False
            logger.warning(f'cannot grab {project.name} folder ID from egnyte link for update b/c link is not direct link.')
        return folder_id
    #endregion
    #region folders
        #region new
    def get_folder_from_id(self, folder_id:str) -> str:
            '''uses folder id to find folder (used to extrapolate path, but could do more)'''
            url = f"https://dowbuilt.egnyte.com/pubapi/v1/fs/ids/folder/{folder_id}"
            headers = CaseInsensitiveDict()
            headers["Authorization"] = f"Bearer {egnyte_token}"
            get_folder_resp = requests.get(url, headers=headers)
            return self.return_dict_from_api_resp(get_folder_resp, 'get_folder_dict')
    def create_folder(self, project:ProjectObj) -> dict:
        '''uses api to create folder'''
        url=f'https://dowbuilt.egnyte.com/pubapi/v1/fs/{project.eg_path}'
        
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
    def restrict_move_n_delete(self, project:ProjectObj) -> dict:
        '''changes default setting so full owners cannot move/delete root folder, just folders inside'''
        url = f"https://dowbuilt.egnyte.com/pubapi/v1/fs/{project.eg_path}"

        headers = CaseInsensitiveDict()
        headers["Authorization"] = f"Bearer {egnyte_token}"
        headers["Content-Type"] = "application/json"        

        data = '{"restrict_move_delete": "true"}'       

        restriction_api_resp= requests.patch(url, headers=headers, data=data)
        return self.return_dict_from_api_resp(restriction_api_resp, 'restriction_api_dict')
    def generate_folder_link(self, project:ProjectObj):
        '''gets folder, finds id, and then attaches to project object to be posted from ss_client'''
        url = f"https://dowbuilt.egnyte.com/pubapi/v1/fs/{project.eg_path}"

        headers = CaseInsensitiveDict()
        headers["Authorization"] = f"Bearer {egnyte_token}"


        get_folder_api_resp = requests.get(url, headers=headers)
        get_folder_api_dict = self.return_dict_from_api_resp(get_folder_api_resp, 'get_folder_api_dict')
        id = get_folder_api_dict.get("folder_id")
        project.eg_link  = 'https://dowbuilt.egnyte.com/navigate/folder/' + id    
        #endregion
        #region update
    def generate_folder_update_url(self, folder_id:str) -> str:
        '''generates the url the api needs in the folder name change post request'''
        api_url = 'https://dowbuilt.egnyte.com/pubapi/v1/fs'
        # Changing spaces back to %20
        url_path = re.sub("\s", "%20", self.handle_cached_paths(folder_id))
        return api_url + url_path
    def change_folder_name(self, folder_id:str)-> dict:
            headers = CaseInsensitiveDict()
            headers["Authorization"] = f"Bearer {egnyte_token}"
            headers["Content-Type"] = "application/json"

            data = '{"action":"move", "destination":"' + f"{self.handle_cached_paths(folder_id)}" + '"}'

            folder_name_change_resp = requests.post(self.generate_folder_update_url(folder_id), headers=headers, data=data)
            return self.return_dict_from_api_resp(folder_name_change_resp, 'folder_name_change_dict')
        #endregion
    #endregion
    #region permissions groups
        #region new
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
        logger.info(f"Configuring Folder Permissions for {project.name}...")
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
        #region update
    def generate_permissions_url(self, folder_id:str) -> str:
        api_url = 'https://dowbuilt.egnyte.com/pubapi/v2/perms'
        # Changing spaces back to %20
        url_path = re.sub("\s", "%20", self.handle_cached_paths(folder_id))
        return api_url + url_path
    def folderid_to_permission_report(self, folder_id:str) -> dict:
        'uses the folder id to see the permissions set on it, and their ids'
        try:
            headers = CaseInsensitiveDict()
            headers["Authorization"] = f"Bearer {egnyte_token}"
            permissions_report_resp = requests.get(self.generate_permissions_url(folder_id), headers=headers)
            permissions_report_dict = self.return_dict_from_api_resp(permissions_report_resp, 'permissions_report_dict')
            return permissions_report_dict
        except:
            logger.warning("generated permission url did not yield folder that existed")
            return False
    def process_project_permission_report(self, permissions_report_dict:dict) -> str:
        '''looks at permission on folder and returns the first group with full permission (that doesn't say state/projects), 
        this is not a very exacting way to find the correct permission group!'''
        permission_list = []
        try:
            for group, permissions_state in permissions_report_dict.get('groupPerms').items():
                if permissions_state == "Full":
                    permission_list.append(group)
            for item in permission_list:
                # state/projects w first letter removed to avoid case sensitivity
                if item.find("tate") == 0:
                    permission_list.remove(item)
                if item.find("rojects") == 0:
                    permission_list.remove(item)
            return permission_list[0]
        except:
            logger.warning("no group has full permissions in this folder")
            return False
    def find_id_from_group_name(self, main_permission_group:str) -> int:
        '''not sure what the first line does, but ult. extracts id from permission group name'''
        url_group_name = re.sub("\s", "%20", main_permission_group)
        url = 'https://dowbuilt.egnyte.com/pubapi/v2/groups?filter=displayName%20eq%20"' + f"{url_group_name}" + '"'
        headers = CaseInsensitiveDict()
        headers["Authorization"] = f"Bearer {egnyte_token}"
        permission_group_resp = requests.get(url, headers=headers)
        permission_group_dict = self.return_dict_from_api_resp(permission_group_resp, 'permission_group_dict')
        id = permission_group_dict.get("resources")[0].get("id")
        return id
    def return_group_id_to_update(self, folder_id:str) -> tuple[str, str]:
        '''looks at permission on folder and returns the first group with full permission, translating from name to group_id 
        this is not a very exacting way to find the correct permission group!'''
        permissions_report_dict = self.folderid_to_permission_report(folder_id)
        if permissions_report_dict:
            main_permission_group = self.process_project_permission_report(permissions_report_dict)
            if main_permission_group:
                id = self.find_id_from_group_name(main_permission_group)
                return id, main_permission_group 
        
        # because empty strings are falsey
        return "", ""
    def change_permission_group_name(self, group_id:str, correct_project_name:str):
            url = 'https://dowbuilt.egnyte.com/pubapi/v2/groups/' + f"{group_id}" 
            headers = CaseInsensitiveDict()
            headers["Authorization"] = f"Bearer {egnyte_token}"
            headers["Content-Type"] = "application/json"

            data = '{"displayName": "' + f"{correct_project_name}" '"}'
            change_group_name_resp = requests.patch(url, headers=headers, data=data)
            return self.return_dict_from_api_resp(change_group_name_resp, 'change_group_name_dict')
    def get_permission_group_members(self, group_id:str) -> dict:
        url = f"https://dowbuilt.egnyte.com/pubapi/v2/groups/{group_id}"

        headers = CaseInsensitiveDict()
        headers["Authorization"] = f"Bearer {egnyte_token}"


        permission_group_resp= requests.get(url, headers=headers)
        return self.return_dict_from_api_resp(permission_group_resp, 'permission_group_dict')
    def identify_permission_updates(self, permission_group_dict:dict, project) -> list:
        """
        Identify permission updates for a project.

        This function compares the members of the main project's permission group 
        with the user emails associated with the project. It checks if there are 
        any project users who are not already in the permission group. Users not 
        in the group are added to the updates list.

        Parameters:
            permission_group_dict (dict): A dictionary containing permission group details, 
                                          including a list of members with their IDs.
            project: An object containing project details, including a list of user emails.

        Returns:
            list: A list of user emails that need to be added to the permission group.
        """
        users_in_group = []
        for user in permission_group_dict.get("members"):
            users_in_group.append(user.get("value"))

        user_updates_list = []
        for user in project.user_emails:
            for account in self.eg_user_list:
                if user == account.get("email"):
                    id = account.get("id")
            if id not in users_in_group:
                user_updates_list.append(user)

        return user_updates_list
    def group_member_updates(self, group_id:int, project:ProjectObj) -> list:
        '''takes permission group id, extrapoles members, checks against required users'''
        permission_group_dict = self.get_permission_group_members(group_id)
        if permission_group_dict:
            user_updates_list = self.identify_permission_updates(permission_group_dict, project)
            return user_updates_list
        return []
    def execute_group_changes(self, updates:list, group_id:int):
        '''manages adding individuals to permission group, executing on them one by one by finding their egnyte id and then doing the api call'''
        for user in updates:
            for user_data in self.eg_user_list:
                if user == user_data.get("email"):
                    logger.debug(f'adding {user_data.get("name")} to permission group')
                    self.update_group_members_api(user_data.get("id"), group_id)
    def update_group_members_api(self, user_id:int, group_id:int):
        '''adds user to a particular permission group'''
        url = f"https://dowbuilt.egnyte.com/pubapi/v2/groups/{group_id}"

        headers = CaseInsensitiveDict()
        headers["Authorization"] = f"Bearer {egnyte_token}"
        headers["Content-Type"] = "application/json"

        data = '{"members":[{"value":'+ str(user_id) + '}]}'

        group_change_resp = requests.patch(url, headers=headers, data=data)
        group_change_dict = self.return_dict_from_api_resp(group_change_resp, 'group_change_dict')
        #endregion
    #endregion


if __name__ == "__main__":
    pass