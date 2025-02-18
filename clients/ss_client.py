#region imports and variables
# Check if we are on a dev computer or server
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
from dataclasses import dataclass, field
from typing import Optional, Tuple, List
from pathlib import Path
import logging
from clients.grid import grid
from configs.setup_logger import setup_logger
logger = setup_logger(__name__, level=logging.DEBUG)
ss_config = json.loads(Path("configs/ss_config.json").read_text())
smartsheet_admin_token = ss_config["smartsheet_admin_token"]
smart = smartsheet.Smartsheet(access_token=smartsheet_admin_token)
smart.errors_as_exceptions(True)
grid.token=smartsheet_admin_token
#endregion

#region Models
@dataclass
class ProjectObj:
    enum: str
    saas_row_id:str
    name: str
    region: str
    job_type: str
    regional_sheet_id: str
    ss_link: str
    eg_link: str
    eg_path: str
    action_type: str
    need_update: bool
    ss_workspace_name: str
    need_new_ss: bool
    need_new_eg: bool
    users: List[str]
    user_emails: List[str]
    state: str

    def __repr__(self):
        return (
            f"\n----------------\n"
            f"PROJECT: {self.name}\n\n"
            f"name: {self.name}, enum: {self.enum}, saas_row_id={self.saas_row_id}\n"
            f"region: {self.region}, state: {self.state}\n"
            f"users: {', '.join(self.users)}\n" 
            f"user_emails: {', '.join(self.user_emails)}\n"
            f"action_type: {self.action_type}, need_update: {self.need_update},\n"
            f"need_new_eg: {self.need_new_eg}, need_new_ss: {self.need_new_ss}\n"
            f"eg_link: {self.eg_link}\n"
            f"ss_link: {self.ss_link}\n"
            f"----------------"
        )
@dataclass
class PostingData:
    regional_sheet_id: str
    regional_row_id: int
    post: list[dict] # List of {'column_id': int, 'link': str}
#endregion

class SmartsheetClient():
    '''words'''
    def __init__(self):
        logger.debug('Initializing Smartsheet Client...')
        self.ss_link = ""
        self.cached_sheets = {
            'SAAS':None,
            'HI': None,
            'NY': None,
            'NORCAL': None,
            'SOCAL': None,
            'WA': None,
            'FL': None,
            'MTN': None,
            'ATX': None,
            'NE': None
        }
#region helpers
    def try_except_pattern(self, value:str) -> str:
        '''wraps "value" in a try/accept format. used when pulling  info from DF because blank columns are not added to df, so you must try/except each df inquiry'''
        try:
            true_value = value
            if str(true_value) == "None":
                true_value = "none"
        except:
            true_value = "none"
        
        return true_value
#endregion
#region get_data 
    #region building_proj_obj helpers
    def get_relevent_smartsheets(self, saas_row_id: str) -> tuple[grid, grid, str]:
        """
        Loads relevant DataFrames and returns them along with region and sheet ID.

        Args:
            saas_row_id: The row ID from the SaaS sheet.

        Returns:
            A tuple containing:
            - The SaaS sheet instance.
            - The regional sheet instance.
            - The sheet ID string (used to grab highly specific email data from the regional sheet).
        """
        saas_sheet = self.handle_cached_smartsheets(region='SAAS', sheet_id=ss_config['saas_id'])
        region = self.region_from_saas_rowid(saas_row_id, saas_sheet.df)
        regional_sheet_id = ss_config['regional_sheetid_obj'][region]
        regional_sheet = self.handle_cached_smartsheets(region, regional_sheet_id)
        return saas_sheet, regional_sheet, regional_sheet_id
    def filter_to_relevent_row(self, saas_sheet: grid, regional_sheet: grid, enum:str, saas_row_id:str) -> tuple[pd.Series, pd.Series]:
        """
        Filteres the smartsheet data to the correct enunerator/sheet id so we have easy to use row data

        Args:
            saas_sheet: The SaaS sheet instance.
            regional_sheet: The regional sheet instance.
            enum: The enumerator string.
            saas_row_id: the row id in the saas smartsheet corresponding to the request

        Returns:
            A tuple containing:
            - The project row DataFrame.
            - The SaaS row Series.
        """
        
        proj_row = regional_sheet.df.loc[regional_sheet.df['ENUMERATOR'] == enum].iloc[0]
        if proj_row.empty:
            logger.warning(f"No project data found for ENUMERATOR @ regional PL: {enum}")

        saas_row = saas_sheet.df.loc[saas_sheet.df['id'] == saas_row_id].iloc[0]
        if saas_row.empty:
            logger.warning(f"No project data found for ENUMERATOR @ saas admin: {enum}")

        return proj_row, saas_row
    def process_permission_users(self, proj_row:pd.Series):
        '''takes a df that is filtered to one specific enumerator that we need to grab info on 
        grabs users of all roles (from regional sheet), also looks at addtional permission users'''
        roles = ['PM', 'PE', 'SUP', 'FM', 'NON SYS Created By']
        users = [self.try_except_pattern(proj_row[col]) for col in roles]

        # Additional permissions
        addtl_permission = self.try_except_pattern(
            proj_row["Platform Containers addt'l Permissions"]
        ).split(", ")
        if isinstance(addtl_permission, list):
            users.extend(addtl_permission)

        # Deduplicate and filter invalid names
        users = list(set(users))  # Remove duplicates
        users = [
            name for name in users
            if name and not name.startswith(("_", "future")) and name.lower() != "none"
        ]

        return users
    def process_permission_emails(self, proj_row:pd.Series, regional_column_df:pd.DataFrame, sheet_id: str):
        '''Extracts and processes user emails from regional sheet'''

        if proj_row["REGION"] == 'HI':
            ss_config['user_column_names'].append("PRINCIPAL")

        user_column_ids = []
        for column in ss_config['user_column_names']:
            matching_rows = regional_column_df.loc[regional_column_df['title'] == column]
            if matching_rows.empty:
                logger.debug(f"Column df for {proj_row['REGION']} did not return value for column '{column}'")
                continue  # Skip this column if no match is found
            user_column_ids.append(matching_rows['id'].iloc[0])


        # Fetch and process the reduced sheet data
        reduced_sheet = smart.Sheets.get_sheet(
            sheet_id,
            row_ids=proj_row['id'],
            column_ids=user_column_ids,
            level='2',
            include='objectValue'
        ).to_dict()

        # Extract emails from reduced rows
        reduced_rows = [row.get('cells') for row in reduced_sheet.get('rows', [])]
        email_data = self.filter_value_by_type(reduced_rows, 'objectValue')
        email_list = self.extract_emails(email_data)
        # Extract emails and filter unwanted entries
        processed_emails = [
            email for email in email_list if not any(sub in email for sub in ('future', 'tbd'))
        ]

        return processed_emails or ['arielv@dowbuilt.com']
    def filter_value_by_type(self, rows, key: str):
        '''Extracts values from rows based on a specified key.'''
        return [[cell.get(key) for cell in row] for row in rows]
    def extract_emails(self, email_data:list):
        '''Extracts user emails from email object'''
        emails = []

        for sublist in email_data:  # Iterate over the outer list
            for entry in sublist:  # Iterate over each dictionary in the inner list
                # Check if the entry has 'values' and extract emails from the nested dictionaries
                if isinstance(entry, dict) and "values" in entry:
                    emails.extend(
                        value["email"]
                        for value in entry["values"]
                        if isinstance(value, dict) and "email" in value
                    )
        return list(set(emails))
    #endregion
    def build_proj_obj(self, saas_row_id: int) -> ProjectObj:
        """
        Builds the ProjectObj object that guides the action phase of this class (from SaaS admin sheet).

        Args:
            sheet_obj: Smartsheets instance used for interacting with sheets.
            saas_row_id: The row ID from the SaaS sheet that identifies the project.

        Returns:
            A fully initialized ProjectObj containing project-specific details.
        """

        # Step 1: Get sheet data
        saas_sheet, regional_sheet, regional_sheet_id = self.get_relevent_smartsheets(saas_row_id)

        # Step 2: Filter to specific project and SaaS row
        enum = saas_sheet.df.loc[saas_sheet.df['id'] == saas_row_id].iloc[0]['ENUMERATOR']
        proj_row, saas_row = self.filter_to_relevent_row(saas_sheet, regional_sheet, enum, saas_row_id)

        # Step 3: Process users and emails
        users = self.process_permission_users(proj_row)
        user_emails = self.process_permission_emails(proj_row, regional_sheet.column_df, regional_sheet_id)

        # Step 4: Create and return the ProjectObj
        project_obj = ProjectObj(
            enum=enum,
            saas_row_id=saas_row_id,
            name=proj_row['FULL NAME'],
            region=proj_row['REGION'],
            job_type=proj_row['JOB TYPE'],
            regional_sheet_id=regional_sheet_id,
            ss_link=proj_row['SMARTSHEET'],
            eg_link=proj_row['EGNYTE'],
            eg_path='tbd',
            action_type=saas_row['ADMINISTRATIVE Action Type'],
            need_update=(saas_row['Update Conditional'] == '1'),
            ss_workspace_name=f"Project_{proj_row['FULL NAME'][:35]}_{enum}",
            need_new_ss=(not proj_row['SMARTSHEET'] and saas_row['SM Conditional'] == '1'),
            need_new_eg=(not proj_row['EGNYTE'] and saas_row['EGN Conditional'] == '1'),
            users=users,
            user_emails=user_emails,
            state=proj_row['STATE']
        )

        return project_obj
    def handle_cached_smartsheets(self, region: str, sheet_id: str) -> grid:
        """
        Checks if the regional grid object has already been loaded.
        If not, loads it and caches it.

        Args:
            region (str): The name of the region to check and load.
            sheet_id (str): The ID of the Smartsheet for the region.

        Returns:
            grid: The loaded or existing grid object for the specified region.
        """

        # Normalize the region name to handle special cases (e.g., MTN)
        obj_region = region.replace('.', '')

        # Check if the DataFrame for the region is already loaded
        sheet = self.cached_sheets[obj_region]

        if sheet is None:
            # Load the DataFrame (replace this with your actual loading logic)
            logger.info(f"Fetching the {region} Smartsheet...")
            sheet = grid(sheet_id)
            sheet.fetch_content()
            self.cached_sheets[obj_region] = sheet

        return sheet
#endregion
#region sheets
    def region_from_saas_rowid(self, saas_row_id: int, saas_sheet_df:pd.DataFrame) -> str:
        '''given an enumerator (project), finds the region and then sheet id of for that region's Regional Project List'''
        saas_row= saas_sheet_df.loc[saas_sheet_df['id'] == saas_row_id].iloc[0]
        region = saas_row['REGION']
        return region
#endregion
#region workspaces
    def save_as_new_wrkspc(self, template_id: str, name:str) ->dict:
        '''makes new workspace from another one as the template'''
        return smart.Workspaces.copy_workspace(
            template_id,           # workspace_id
            smartsheet.models.ContainerDestination({
                'new_name': f"{name}"
                })
            ).to_dict()
    def get_wrkspcs(self) -> dict:
        return smart.Workspaces.list_workspaces(include_all=True).to_dict()
    def get_wrkspc_from_project_link(self, project: ProjectObj) -> dict:
        '''generates a list of all workspaces, searches for a workspace with the given SS link and then returns the associated ID'''
        wrkspc = None
        get_workspace_data = self.get_wrkspcs()
        workspace_list = get_workspace_data.get('data')
        for workspace in workspace_list:
            if workspace.get("permalink") == project.ss_link:
                wrkspc = workspace
        if project.ss_link == "none":
            logger.debug('SS workspace update skipped due to lack of workspace existance')
        elif wrkspc == None: 
            logger.warning(f'Permissions Error: Workspace not found from link ({project.ss_link})')
        return wrkspc
    def rename_wrkspc(self, wrkspc_id:int, name:str):
        logger.info('renaming the workspace...')
        self.updated_workspace = smart.Workspaces.update_workspace(
         wrkspc_id,       # workspace_id
         smartsheet.models.Workspace({
           'name': f"{name}"
         })
        )
    def audit_wrkspc_isnew(self):
        self.isnew_bool=True
        response = smart.Workspaces.list_workspaces(include_all=True)
        for workspace in response.to_dict().get("data"):
            if workspace.get("name") == f'Project_{self.proj_dict.get("name")}_{self.proj_dict.get("enum")}':
                self.isnew_bool = False
                logger.info(f'a workspace audit within smartsheet revealed that Project_{self.proj_dict.get("name")}_{self.proj_dict.get("enum")} already exists')  
    def wrkspc_shares_need_updating(self, project:ProjectObj, wrkspc_id: int) -> bool:
        '''returns true if the workspace is missing user in shares group'''
        response = smart.Workspaces.list_shares(
            wrkspc_id,       # workspace_id
            include_all=True)
        current_shares = [share.get('name') for share in response.to_dict()['data']]
        required_shares = project.users
        required_shares.extend(['Smartsheet Admin', 'Project-Admins', 'Project-Review', 'Field_Admins'])
        for share in required_shares:
            if share not in current_shares:
                return True
        return False 
    def ss_permission_setting(self, project: ProjectObj, wrkspc_id: int):
        '''sharing the workspace with those who need it + standard project admin'''
        logger.info('Configuring Workspace permissions...')
        email_list = project.user_emails
        shares = [
            {'type': 'email', 'value': email, 'access_level': 'ADMIN'} for email in email_list
        ] + [
            {'type': 'groupId', 'value': ss_config['field_admins_id'], 'access_level': 'ADMIN'},
            {'type': 'groupId', 'value': ss_config['project_admins_id'], 'access_level': 'ADMIN'},
            {'type': 'groupId', 'value': ss_config['project_review_id'], 'access_level': 'EDITOR'}
        ]

        for share in shares:
            share_data = smartsheet.models.Share({
                'access_level': share['access_level'],
                share['type']: share['value']
            })

            try:
                smart.Workspaces.share_workspace(wrkspc_id, share_data)
            except ApiError:
                if share['type'] == 'email':
                    logger.debug(f"{share['value']} already has access to workspace")
                else:
                    group_name = share['value']
                    logger.debug(f"{group_name} already has access to workspace")
#endregion
#region posting 
    def generate_posting_data(self, project: ProjectObj) -> PostingData:
        """Generates PostingData for the project."""
        sheet = self.handle_cached_smartsheets(project.region, ss_config["regional_sheetid_obj"][project.region])
        sheet_columns = sheet.get_column_df()

        # Retrieve required IDs
        eg_column_id = sheet_columns.loc[sheet_columns['title'] == "EGNYTE", "id"].squeeze()
        ss_column_id = sheet_columns.loc[sheet_columns['title'] == "SMARTSHEET", "id"].squeeze()
        regional_row_id = sheet.df.loc[sheet.df['ENUMERATOR'] == project.enum, "id"].squeeze()

        # Populate links list based on conditions
        post = []
        if project.need_new_eg:
           post.append({'column_id': int(eg_column_id), 'link': project.eg_link})
        if project.need_new_ss:
            post.append({'column_id': int(ss_column_id), 'link': project.ss_link})

        return PostingData(
            regional_sheet_id=project.regional_sheet_id,
            regional_row_id=int(regional_row_id),
            post=post
        )
    def post_resulting_links(self, project:ProjectObj):
        '''posts links that were created to the regional Project List'''
        posting_data = self.generate_posting_data(project)
        
        new_row = smart.models.Row()
        new_row.id = posting_data.regional_row_id

        for cell in posting_data.post:
            new_cell = smart.models.Cell()
            new_cell.column_id = cell.get("column_id")
            new_cell.value = cell.get("link")
            new_cell.strict = False
            new_row.cells.append(new_cell)

        if new_row.cells:
            response = smart.Sheets.update_rows(posting_data.regional_sheet_id, [new_row])
            if response.message == "SUCCESS":
                logger.info(f'Link-post into {project.region} Project List complete')
            else:
                logger.warning("Looks like links didn't post! Check ss_client.post_resulting_links for bugs.")
    def post_update_checkbox(self, saas_row_id:int):
        '''checks checkbox for more recent item with given enum for updatings (this could get buggy if two back to back requests exist)'''
        new_cell = smart.models.Cell({'column_id' : ss_config['saas_update_check_column_id'], 'value': "1", 'strict': False})
        new_row = smart.models.Row({'id':saas_row_id})
        new_row.cells.append(new_cell)

        if str(new_row.to_dict().get("cells")) != "None":
            # Update rows
            updated_row = smart.Sheets.update_rows(
              ss_config['saas_id'],      # sheet_id
              [new_row])
            if updated_row.message == 'SUCCESS':
                logger.info(f'checked update bool in Saas Admin Page')
            else:
                logger.info(f'update bool checkbox posting had result of {updated_row.message}')
#endregion

if __name__ == "__main__":
    pass
