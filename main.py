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
eg_config = json.loads(Path("configs/eg_config.json").read_text())
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
#endregion

ss_client = SmartsheetClient()
eg_client = EgnyteClient()

def new_ss_workspace(project: ProjectObj):
    '''this uses the SS client to create a new project workspace from the template, giving it appropriate permissions and then posting the link back to the project list'''
    logger.info(f"Creating Smartsheet Workspace for {project.name}...")
    new_wrkspc = ss_client.save_as_new_wrkspc(ss_config['wkspc_template_id'], project.ss_workspace_name)
    new_wrkspc_id = new_wrkspc.get("data").get("id")
    project.ss_link = new_wrkspc_id = new_wrkspc.get("data").get("permalink")
    ss_client.ss_permission_setting(project, new_wrkspc_id)
    logger.info("SS creation complete")
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

    logger.info("SS update complete")
def new_eg_folder(project:ProjectObj):
    '''generates path to new folder, creates folder from path, generates new permission group with users, shares various permission groups to folder, copies template, restricts delete, generates link and posts it to ss'''
    logger.info(f"Creating Egnyte Folder for {project.name}...")
    eg_client.generate_eg_project_path(project)
    new_folder = eg_client.create_folder(project)
    permission_members = eg_client.prepare_new_permission_group(project)
    permission_group_id = eg_client.generate_permission_group(permission_members, project)
    folder_permission_api_dict = eg_client.set_permissions_on_new_folder(project)
    folder_move_api_dict = eg_client.copy_folders_to_new_location(source_path = eg_config['eg_template_path'], destination_path = project.eg_path)
    restrict_api_dict = eg_client.restrict_move_n_delete(project)
    posting_data = eg_client.generate_folder_link(project)
    logger.debug('EG creation complete')
def update_eg_folder(project:ProjectObj):
    '''words'''
    correct_project_name = project.name + "_" + project.enum
    logger.info(f"updating Egnyte for {project.name}")
    folder_id = eg_client.generate_id_from_url(project)
    if folder_id:
        #update permission group
        group_id, group_name = eg_client.return_group_id_to_update(folder_id)
        if group_id and group_name:
            if group_name != correct_project_name + "_" + project.enum:
                eg_client.change_permission_group_name(group_id, group_name)
            updates = eg_client.group_member_updates(group_id, project)
            if updates:
                eg_client.execute_group_changes(updates, group_id)
        
        #update folder name/location
            if correct_project_name not in eg_client.handle_cached_paths(folder_id):   
                logger.info(f"debugging folder_id: {folder_id}")
                eg_client.change_folder_name(folder_id)
    
        logger.info("EG update complete")
        return 
    logger.warning('project update was skipped')
def main_per_row(saas_row_id:int):
    '''grabs data, optionally adds/updates ss/eg, posts'''
    project = ss_client.build_proj_obj(
        saas_row_id=saas_row_id)
    logger.info(project)
    
    if project.need_new_ss:
        new_ss_workspace(project)

    if project.need_new_eg:
        new_eg_folder(project)

    if project.need_new_eg or project.need_new_ss:
        ss_client.post_resulting_links(project)

    if project.need_update:
        update_eg_folder(project)
        update_ss_workspace(project)
        ss_client.post_update_checkbox(saas_row_id)
        
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

main()