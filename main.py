#region imports and variables
import os
import sys
from datetime import datetime
import json
import re
import pandas as pd
import os
from dataclasses import dataclass
from typing import Optional
from pathlib import Path
ss_config = json.loads(Path("configs/ss_config.json").read_text())
# Add the parent directory of V3 to sys.path
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from clients.ss_client import SmartsheetClient, ProjectObj, PostingData

# Check if we are on a dev computer or server
if os.name == 'nt':
    sys.path.append(r"Z:\Shared\IT\Projects and Solutions\Python\Ariel\_Master")
else:
    sys.path.append(os.path.expanduser(r"~/_Master"))

# Import master_logger, master_smartsheet_grid, and master_globals
try:
    from master_logger import ghetto_logger 
    from master_smartsheet_grid import grid 
except ImportError as e:
    print(f"Error importing module: {e}")
    sys.exit(1)
#endregion

eg_config = {
    # 'egnyte_token':sensative_egnyte_token,
    # group ids (that need to be part of all projects)
    'field_admins_id':  2077914675079044,
    'project_admins_id': 2231803353294724,
    'project_review_id': 1394789389232004,
    'pythscript_checkbox_column_id': 1907059135932292
    }

log=ghetto_logger("main.py")
ss_client = SmartsheetClient(log=log, config=None)
# eg_client = EgnyeClient(eg_config, log)

def new_ss_workspace(project: ProjectObj, posting_data:PostingData):
    '''this uses the SS client to create a new project workspace from the template, giving it appropriate permissions and then posting the link back to the project list'''
    log.log(f"Creating Smartsheet Workspace for {project.name}")
    testing_workspace_name = f"ProjectTESTING_{project.name[:28]}_{project.enum}"
    new_wrkspc = ss_client.save_as_new_wrkspc(ss_config.wkspc_template_id, project.ss_workspace_name)
    new_wrkspc_id = new_wrkspc.get("data").get("id")
    ss_client.ss_permission_setting(project, new_wrkspc_id),
    posting_data_updated = ss_client.get_new_post_ids(project, posting_data)
    log.log("ss creation complete")
    return posting_data_updated
def update_ss_workspace(project:ProjectObj):
    '''updates an existing workspace with the current information, changes name if needed, changes permissions if needed'''
    log.log(f"Updating Smartsheet Workspace for {project.name}")
    wrkspc = ss_client.get_wrkspc_from_project_link(project)
    if wrkspc is None:
        log.log("Smartsheet update not needed (workspace not found).")
        return

    if wrkspc.get('name') != project.ss_workspace_name:
        ss_client.rename_wrkspc(wrkspc['id'], project.ss_workspace_name),
    
    if ss_client.wrkspc_shares_need_updating(project, wrkspc['id']):
        ss_client.ss_permission_setting(project, wrkspc['id'])

    log.log("ss update complete")
def new_eg_folder(project:ProjectObj, posting_data: PostingData):
    '''words'''
    pass
def update_eg_folder(project:ProjectObj):
    '''words'''
    pass
def main_per_row(saas_row_id:int):
    '''grabs data, optionally adds/updates ss/eg, posts'''
    project = ss_client.build_proj_obj(
        saas_row_id=saas_row_id)
    log.log(project)
    posting_data = PostingData()
    
    if project.need_update:
        update_eg_folder(project)
        posting_data = update_ss_workspace(project)
        ss_client.post_update_checkbox(saas_row_id)
    
    if project.need_new_ss:
        posting_data = new_ss_workspace(project, posting_data)

    if project.need_new_eg:
        posting_data = new_eg_folder(project,posting_data)

    if project.need_new_eg or project.need_new_ss:
        ss_client.post_resulting_links(project, posting_data)
        
def identify_open_saas_rows():
    '''makes a df from the saas sheet (https://app.smartsheet.com/sheets/4X2m4ChQjgGh2gf2Hg475945rwVpV5Phmw69Gp61?view=grid&filterId=7982787065079684) 
    and looks for open rows, returns ids, names, and enums in three lists'''
    saas_sheet = ss_client.handle_cached_smartsheets(region='SAAS', sheet_id=ss_client.saas_id)
    open_rows = saas_sheet.df.loc[saas_sheet.df['Saas Status'] == 'Open']
    return (
        open_rows['id'].values.tolist(),
        open_rows['New Name'].values.tolist(),
        open_rows['ENUMERATOR'].values.tolist()
    )
def main():
    '''takes open rows and then loops through, pushing each through the main func'''
    saas_row_ids, project_names, enums = identify_open_saas_rows()
    for i, (saas_row_id, project_name, enum) in enumerate(zip(saas_row_ids, project_names, enums), start=1):
        log.log(f"{i}/{len(saas_row_ids)}: {project_name}")
        main_per_row(saas_row_id)
    log.log('finished!')

main()
