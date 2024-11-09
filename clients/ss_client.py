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
from dataclasses import dataclass
from typing import Optional, Tuple, List
from pathlib import Path
ss_config = json.loads(Path("configs/ss_config.json").read_text())
breakpoint()
# Check if we are on a dev computer or server
if os.name == 'nt':
    sys.path.append(r"Z:\Shared\IT\Projects and Solutions\Python\Ariel\_Master")
else:
    sys.path.append(os.path.expanduser(r"~/_Master"))

# Import master_logger, master_smartsheet_grid, and master_globals
try:
    from master_logger import ghetto_logger
    from master_smartsheet_grid import grid
    from master_globals import smartsheet_admin_token
except ImportError as e:
    print(f"Error importing module: {e}")
    sys.exit(1)
#endregion

#region Models
@dataclass
class ProjectObj:
    enum: str
    saas_row_id:str
    name: str
    region: str
    regional_sheet_id: str
    ss_link: str
    eg_link: str
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
            f"----------------\n"
        )

@dataclass
class PostingData:
    need_update_column_id: Optional[int] = None
    saas_admin_sheet_id: Optional[int] = None
    saas_admin_row_id: Optional[int] = None
    regional_sheet_id: Optional[int] = None
    regional_row_id: Optional[int] = None
    eg_column_id: Optional[int] = None
    eg_link: Optional[str] = None
    ss_column_id: Optional[int] = None
    ss_link: Optional[str] = None
#endregion


class SmartsheetClient():
    '''words'''
    def __init__(self, log, config:dict = None):
        if config is None:
            config = default_ss_config
        self.apply_config(config)
        self.log=log
        self.smart = smartsheet.Smartsheet(access_token=self.smartsheet_token)
        self.smart.errors_as_exceptions(True)
        grid.token=self.smartsheet_token
        self.ss_link = ""
        self.log.log('Initializing Smartsheet Client...')
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
    def apply_config(self, config:dict):
        '''turns all config items into self.key = value'''
        for key, value in config.items():
            setattr(self, key, value)
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
        saas_sheet = self.handle_cached_smartsheets(region='SAAS', sheet_id=self.saas_id)
        region = self.region_from_saas_rowid(saas_row_id, saas_sheet.df)
        regional_sheet_id = self.regional_sheetid_obj[region]
        regional_sheet = self.handle_cached_smartsheets(region, regional_sheet_id)
        return saas_sheet, regional_sheet, regional_sheet_id
    def filter_to_relevent_row(self, saas_sheet: grid, regional_sheet: grid, enum:str, saas_row_id:str) -> tuple[str, pd.Series, pd.Series]:
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
            self.log.log(f"No project data found for ENUMERATOR @ regional PL: {enum}")

        saas_row = saas_sheet.df.loc[saas_sheet.df['id'] == saas_row_id].iloc[0]
        if saas_row.empty:
            self.log.log(f"No project data found for ENUMERATOR @ saas admin: {enum}")

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
            self.user_column_names.append("PRINCIPAL")

        user_column_ids = [
            regional_column_df.loc[regional_column_df['title'] == column]['id'].iloc[0]
            for column in self.user_column_names
        ]
        # Fetch and process the reduced sheet data
        reduced_sheet = self.smart.Sheets.get_sheet(
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
    def build_proj_obj(self, saas_row_id: str) -> ProjectObj:
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
            regional_sheet_id=regional_sheet_id,
            ss_link=proj_row['SMARTSHEET'],
            eg_link=proj_row['EGNYTE'],
            action_type=saas_row['ADMINISTRATIVE Action Type'],
            need_update=(saas_row['Update Conditional'] == '1'),
            ss_workspace_name=f"Project_{proj_row['FULL NAME'][:35]}_{enum}",
            need_new_ss=(str(proj_row['SMARTSHEET']) == "none" and saas_row['SM Conditional'] == '1'),
            need_new_eg=(str(proj_row['EGNYTE']) == "none" and saas_row['EGN Conditional'] == '1'),
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
            self.log.log(f"Fetching the {region} Smartsheet...")
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
    def save_as_new_wrkspc(self, template_id: str, name:str):
        '''makes new workspace from another one as the template'''
        return self.smart.Workspaces.copy_workspace(
            template_id,           # workspace_id
            smartsheet.models.ContainerDestination({
                'new_name': f"{name}"
                })
            ).to_dict()
    def get_wrkspcs(self):
        return self.smart.Workspaces.list_workspaces(include_all=True).to_dict()
    def get_wrkspc_from_project_link(self, project: ProjectObj):
        '''generates a list of all workspaces, searches for a workspace with the given SS link and then returns the associated ID'''
        wrkspc = None
        get_workspace_data = self.get_wrkspcs()
        workspace_list = get_workspace_data.get('data')
        for workspace in workspace_list:
            if workspace.get("permalink") == project.ss_link:
                wrkspc = workspace
        if project.ss_link == "none":
            self.log.log('SS workspace update skipped due to lack of workspace existance')
        elif wrkspc == None: 
            self.log.log(f'Permissions Error: Workspace not found from link ({project.ss_link})')
        return wrkspc
    def rename_wrkspc(self, wrkspc_id:int, name:str):
        self.log.log('renaming the workspace...')
        self.updated_workspace = self.smart.Workspaces.update_workspace(
         wrkspc_id,       # workspace_id
         smartsheet.models.Workspace({
           'name': f"{name}"
         })
        )
    def audit_wrkspc_isnew(self):
        self.isnew_bool=True
        response = self.smart.Workspaces.list_workspaces(include_all=True)
        for workspace in response.to_dict().get("data"):
            if workspace.get("name") == f'Project_{self.proj_dict.get("name")}_{self.proj_dict.get("enum")}':
                self.isnew_bool = False
                self.log.log(f'a workspace audit within smartsheet revealed that Project_{self.proj_dict.get("name")}_{self.proj_dict.get("enum")} already exists')  
    def wrkspc_shares_need_updating(self, project:ProjectObj, wrkspc_id: int):
        '''returns true if the workspace is missing user in shares group'''
        response = self.smart.Workspaces.list_shares(
            wrkspc_id,       # workspace_id
            include_all=True)
        current_shares = [share['name'] for share in response.to_dict()['data']]
        required_shares = project.users
        required_shares.extend(['Smartsheet Admin', 'Project-Admins', 'Project-Review', 'Field_Admins'])
        for share in required_shares:
            if share not in current_shares:
                return True
        return False 
    def ss_permission_setting(self, project: ProjectObj, wrkspc_id: int):
        '''sharing the workspace with those who need it + standard project admin'''
        self.log.log('configuring workspace permissions...')
        email_list = project.user_emails
        shares = [
            {'type': 'email', 'value': email, 'access_level': 'ADMIN'} for email in email_list
        ] + [
            {'type': 'groupId', 'value': self.field_admins_id, 'access_level': 'ADMIN'},
            {'type': 'groupId', 'value': self.project_admins_id, 'access_level': 'ADMIN'},
            {'type': 'groupId', 'value': self.project_review_id, 'access_level': 'EDITOR'}
        ]

        for share in shares:
            share_data = smartsheet.models.Share({
                'access_level': share['access_level'],
                share['type']: share['value']
            })

            try:
                self.smart.Workspaces.share_workspace(wrkspc_id, share_data)
            except ApiError:
                if share['type'] == 'email':
                    self.log.log(f"{share['value']} already has access to workspace")
                else:
                    group_name = share['value']
                    self.log.log(f"{group_name} already has access to workspace")
#endregion
#region posting 
    def get_new_post_ids(self, project:ProjectObj, posting_data:PostingData):
        '''uses the regional sheet id to gather column ids for Egnyte and Smartsheet column and row Id for row with the enum we are working with'''
        sheet = grid(project.regional_sheet_id)
        sheet.fetch_content()
        sheet_columns = sheet.get_column_df()
        row_ids = sheet.grid_row_ids
        sheet.df["id"]=row_ids
        eg_column_id = sheet_columns.loc[sheet_columns['title'] == "EGNYTE"]["id"].tolist()[0]
        ss_column_id = sheet_columns.loc[sheet_columns['title'] == "SMARTSHEET"]["id"].tolist()[0]
        regional_row_id = sheet.df.loc[sheet.df['ENUMERATOR'] == project.enum]["id"].tolist()[0]
        posting_data.regional_sheet_id = project.regional_sheet_id
        posting_data.regional_row_id = regional_row_id
        posting_data.eg_column_id = eg_column_id
        posting_data.eg_link = project.eg_link
        posting_data.ss_column_id = ss_column_id
        posting_data.ss_link = project.ss_link

        return posting_data
    def post_resulting_links(self, project:ProjectObj, posting_data:PostingData):
        '''posts links that were created to the regional Project List'''
        new_row = self.smart.models.Row()
        new_row.id = posting_data.row

        link_list = [{'column_id': posting_data.eg_column_id, 'link': posting_data.eg_link}, {'column_id': posting_data.ss_column_id, 'link': posting_data.ss_link}]
        for item in link_list:
            if item.get("link") != "":
                new_cell = self.smart.models.Cell()
                new_cell.column_id = item.get("column_id")
                new_cell.value = item.get("link")
                new_cell.strict = False

                # Build the row to update
                new_row.cells.append(new_cell)
        if str(new_row.to_dict().get("cells")) != "None":
            # Update rows
            response = self.smart.Sheets.update_rows(
              posting_data.sheet_id,      # sheet_id
              [new_row])
            self.log.log(f'link-post into {project.region} Project List complete')   
    def post_update_checkbox(self, saas_row_id:int):
        '''checks checkbox for more recent item with given enum for updatings (this could get buggy if two back to back requests exist)'''
        new_cell = self.smart.models.Cell({'column_id' : self.saas_update_check_column_id, 'value': "1", 'strict': False})
        new_row = self.smart.models.Row({'id':saas_row_id})
        new_row.cells.append(new_cell)

        if str(new_row.to_dict().get("cells")) != "None":
            # Update rows
            updated_row = self.smart.Sheets.update_rows(
              self.saas_id,      # sheet_id
              [new_row])
            if updated_row.message == 'SUCCESS':
                self.log.log(f'checked update bool in Saas Admin Page')
            else:
                self.log.log(f'update bool checkbox posting had result of {updated_row.message}')
#endregion



if __name__ == "__main__":
    config = {
        'smartsheet_token':smartsheet_admin_token,
        'regional_sheetid_obj':
            {
                "ALL": "3858046490306436",
                "INTAKE": "6270136630962052",
                "HI": "691453002311556",
                "NY": "3506202769418116",
                "NORCAL": "2943252815996804",
                "SOCAL": "5758002583103364",
                "WA": "1254402955732868",
                "FL": "5195052629682052",
                "MTN.": "8009802396788612",
                "ATX": "269240537245572",
                "NE": "5898740071458692"
            },
        'wkspc_template_id':  5301436075534212,
        'automated_wkspc_template_id': 7768425427691396,
        'saas_id': 5728420458981252, 
        'pl30_id': 3858046490306436,
    }
    ss = SmartsheetClient(config)
    enum='02415'
    sheet_id = ss.sheet_id_from_enum(enum)
    obj = ss.build_proj_obj(sheet_id, enum)
    print(obj)
