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

file_name = "eve.xml"
jiraProj = "EVE"
us = "SocialStrata"
repo = "eve"
user = "brianlenz"
token = ""

#purge flag
purge_before_import = "false"

all_xml = read_xml_sourcefile(file_name)
Options = namedtuple("Options", "user account repo token")
opts = Options(user=user, account=us, repo=repo, token=token)

project = Project(jiraProj)

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

if purge_before_import == "true":
  importer.purge_existing_issues()

importer.import_milestones()
importer.import_labels()
importer.import_issues()
importer.post_process_comments()