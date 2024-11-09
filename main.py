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
from clients.eg_client import EgnyteClient
from clients.ss_client import SmartsheetClient, ProjectObj, PostingData
import logging
from configs.setup_logger import setup_logger
logger = setup_logger(__name__, level=logging.DEBUG)
ss_config = json.loads(Path("configs/ss_config.json").read_text())
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
#endregion

ss_client = SmartsheetClient()
eg_client = EgnyteClient()

def new_ss_workspace(project: ProjectObj, posting_data:PostingData):
    '''this uses the SS client to create a new project workspace from the template, giving it appropriate permissions and then posting the link back to the project list'''
    logger.info(f"Creating Smartsheet Workspace for {project.name}")
    new_wrkspc = ss_client.save_as_new_wrkspc(ss_config['wkspc_template_id'], project.ss_workspace_name)
    new_wrkspc_id = new_wrkspc.get("data").get("id")
    ss_client.ss_permission_setting(project, new_wrkspc_id),
    posting_data_updated = ss_client.get_new_post_ids(project, posting_data)
    logger.info("ss creation complete")
    return posting_data_updated
def update_ss_workspace(project:ProjectObj):
    '''updates an existing workspace with the current information, changes name if needed, changes permissions if needed'''
    logger.info(f"Updating Smartsheet Workspace for {project.name}")
    wrkspc = ss_client.get_wrkspc_from_project_link(project)
    if wrkspc is None:
        logger.debug("Smartsheet update not needed (workspace not found).")
        return

    if wrkspc.get('name') != project.ss_workspace_name:
        ss_client.rename_wrkspc(wrkspc['id'], project.ss_workspace_name),
    
    if ss_client.wrkspc_shares_need_updating(project, wrkspc['id']):
        ss_client.ss_permission_setting(project, wrkspc['id'])

    logger.info("ss update complete")
def new_eg_folder(project:ProjectObj, posting_data: PostingData):
    '''words'''
    logger.info(f"Creating Egnyte Folder for {project.name}")
    eg_client.update_eg_project_path(project)
    new_folder = eg_client.create_folder(project.path)
    permission_members = eg_client.prepare_new_permission_group(project)
    permission_group_id = eg_client.generate_permission_group(permission_members, project)
    eg_client.set_permission_on_new_folder
    eg_client.copy_template_to_new_folder
    eg_client.restrict_move_n_delete
    eg_client.generate_folder_link
    eg_client.execute_link_post
def update_eg_folder(project:ProjectObj):
    '''words'''
    pass
def main_per_row(saas_row_id:int):
    '''grabs data, optionally adds/updates ss/eg, posts'''
    project = ss_client.build_proj_obj(
        saas_row_id=saas_row_id)
    logger.info(project)
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
    saas_sheet = ss_client.handle_cached_smartsheets(region='SAAS', sheet_id=ss_config['saas_id'])
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
        logger.info(f"{i}/{len(saas_row_ids)}: {project_name}")
        main_per_row(saas_row_id)
    logger.debug('finished!')

# main()
eg = EgnyteClient()
