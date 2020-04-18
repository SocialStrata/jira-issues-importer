#!/usr/bin/env python

import getpass
from collections import namedtuple
from lxml import objectify
from project import Project
from importer import Importer

def read_xml_sourcefile(file_name):
  all_text = open(file_name).read()
  return objectify.fromstring(all_text)

#file_name = raw_input('Path to JIRA XML query file: ')
#jiraProj = raw_input('JIRA project name to use: ')
#us = raw_input('GitHub account name: ')
#repo = raw_input('GitHub project name: ')
#user = raw_input('GitHub username: ')
#token = raw_input('GitHub token: ')

us = "SocialStrata"
user = "brianlenz"
token = ""

project_configs = [
    {
        'jira_proj': 'CS',
        'repo': 'customer-service',
        'files': ['cs.xml']
    },
    {
        'jira_proj': 'WS',
        'repo': 'web-sites',
        'files': ['ws.xml']
    },
    {
        'jira_proj': 'RS',
        'repo': 'right-starts',
        'files': ['rs.xml']
    },
    {
        'jira_proj': 'HDO',
        'repo': 'hoodo',
        'files': ['hdo.xml']
    },
    {
        'jira_proj': 'EVE',
        'repo': 'eve',
        'files': ['eve1.xml', 'eve2.xml']
    },
    {
        'jira_proj': 'OPS',
        'repo': 'operations',
        'files': ['ops1.xml', 'ops2.xml', 'ops3.xml']
    },
    {
        'jira_proj': 'CRST',
        'repo': 'crowdstack',
        'files': ['crst1.xml', 'crst2.xml', 'crst3.xml', 'crst4.xml', 'crst5.xml', 'crst6.xml', 'crst7.xml', 'crst8.xml', 'crst9.xml', 'crst10.xml', 'crst11.xml', 'crst12.xml', 'crst13.xml', 'crst14.xml', 'crst15.xml', 'crst16.xml', 'crst17.xml', 'crst18.xml']
    }
]

#purge flag
purge_before_import = "false"

importers = []

# bl: first, load the configs
for project_config in project_configs:
    Options = namedtuple("Options", "user account repo token")
    opts = Options(user=user, account=us, repo=project_config['repo'], token=token)

    jira_proj = project_config['jira_proj']
    project = Project(jira_proj)

    for xml_file in project_config['files']:
        all_xml = read_xml_sourcefile(xml_file)
        for item in all_xml.channel.item:
            project.add_item(item)

    project.merge_labels_and_components()
    project.prettify()

    '''
    Steps:
      1. Create any milestones
      2. Create any labels
      3. Create each issue with comments, linking them to milestones and labels
      4: Post-process all comments to replace issue id placeholders with the real ones
    '''
    importer = Importer(opts, project)
    importers.append(importer)

    print 'Found {} issues for {}'.format(len(project.get_issues()), jira_proj)

    # bl: then, create the milestones and labels
    if purge_before_import == "true":
      importer.purge_existing_issues()

    importer.import_milestones()
    importer.import_labels()

    # bl: then, import all of the issues
    importer.import_issues()

# bl: once we've processed everything, then we can process comments so that everything will be linked properly
for importer in importers:
    importer.post_process_comments()