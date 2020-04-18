#!/usr/bin/env python

import requests
import random
import time
import re
import json


class Importer:
  _PLACEHOLDER_PREFIX = "@PSTART"
  
  _PLACEHOLDER_SUFFIX = "@PEND"
  
  _DEFAULT_TIME_OUT = 120.0

  def __init__(self, options, project):
    self.options = options
    self.headers = {  'User-Agent': 'bongohrtech',
                    'Authorization': 'Bearer ' + options.token,
                    'Content-Type': 'application/json'
                    }
    self.project = project
    self.github_url = 'https://api.github.com/repos/' + self.options.account + '/' + self.options.repo
    self.githubGQL_url = 'https://api.github.com/graphql'
    self.jira_issue_replace_patterns = {
        'https://hub.socialstrata.com/jira/browse/' + self.project.name + r'-(\d+)': r'\1',
        self.project.name + r'-(\d+)': r'\1'
    }
    self.jira_issue_url_replace_patterns = {
        'https://hub.socialstrata.com/jira/browse/CRST' + r'-(\d+)': r'https://github.com/SocialStrata/crowdstack/issues/\1',
        'CRST' + r'-(\d+)': r'https://github.com/SocialStrata/crowdstack/issues/\1',
        'https://hub.socialstrata.com/jira/browse/HLA' + r'-(\d+)': r'https://github.com/SocialStrata/crowdstack/issues/\1',
        'HLA' + r'-(\d+)': r'https://github.com/SocialStrata/crowdstack/issues/\1',
        'https://hub.socialstrata.com/jira/browse/OPS' + r'-(\d+)': r'https://github.com/SocialStrata/operations/issues/\1',
        'OPS' + r'-(\d+)': r'https://github.com/SocialStrata/operations/issues/\1',
        'https://hub.socialstrata.com/jira/browse/RS' + r'-(\d+)': r'https://github.com/SocialStrata/right-starts/issues/\1',
        'RS' + r'-(\d+)': r'https://github.com/SocialStrata/right-starts/issues/\1',
        'https://hub.socialstrata.com/jira/browse/EVE' + r'-(\d+)': r'https://github.com/SocialStrata/eve/issues/\1',
        'EVE' + r'-(\d+)': r'https://github.com/SocialStrata/eve/issues/\1',
        'https://hub.socialstrata.com/jira/browse/HDO' + r'-(\d+)': r'https://github.com/SocialStrata/hoodo/issues/\1',
        'HDO' + r'-(\d+)': r'https://github.com/SocialStrata/hoodo/issues/\1',
        'https://hub.socialstrata.com/jira/browse/WS' + r'-(\d+)': r'https://github.com/SocialStrata/web-sites/issues/\1',
        'WS' + r'-(\d+)': r'https://github.com/SocialStrata/web-sites/issues/\1',
        'https://hub.socialstrata.com/jira/browse/CS' + r'-(\d+)': r'https://github.com/SocialStrata/customer-service/issues/\1',
        'CS' + r'-(\d+)': r'https://github.com/SocialStrata/customer-service/issues/\1'
    }
    self.comments_to_append = []
    
  def import_milestones(self):
    """
    Imports the gathered project milestones into GitHub and remembers the created milestone ids
    """
    milestone_url = self.github_url + '/milestones'
    print 'Importing milestones...', milestone_url
    print
    for mkey in self.project.get_milestones().iterkeys():
        data = {'title': mkey}
        r = requests.post(milestone_url, json=data, headers=self.headers, timeout=Importer._DEFAULT_TIME_OUT)
        
        # overwrite histogram data with the actual milestone id now
        if r.status_code == 201:
          content = r.json()
          self.project.get_milestones()[mkey] = content['number']
          print mkey
        else:
          if r.status_code == 422: # already exists
            ms = requests.get(milestone_url + '?state=open', headers=self.headers, timeout=Importer._DEFAULT_TIME_OUT).json()
            ms += requests.get(milestone_url + '?state=closed', headers=self.headers, timeout=Importer._DEFAULT_TIME_OUT).json()
            f = False
            for m in ms:
              if m['title'] == mkey:
                self.project.get_milestones()[mkey] = m['number']
                print mkey, 'found'
                f = True
                break
            if not f:
              exit('Could not find milestone: ' + mkey)
          else:
            print 'Failure!', r.status_code, r.content, r.headers
    
  
  def import_labels(self):
    """
    Imports the gathered project components and labels as labels into GitHub 
    """
    label_url = self.github_url + '/labels'
    print 'Importing labels...', label_url
    print
    for lkey in self.project.get_components().iterkeys():
      data = {'name': lkey, 'color': '%.6x' % random.randint(0, 0xffffff)}
      r = requests.post(label_url, json=data, headers=self.headers, timeout=Importer._DEFAULT_TIME_OUT)
      if r.status_code == 201:
        print lkey
      else:
        print 'Failure importing label ' + lkey, r.status_code, r.content, r.headers

  def import_issues(self):
    """
    Starts the issue import into GitHub:
    First the milestone id is captured for the issue.
    Then JIRA issue relationships are converted into comments.
    After that, the comments are taken out of the issue and 
    references to JIRA issues in comments are replaced with a placeholder    
    """
    print 'Importing issues...'
    for issue in self.project.get_issues():
      
        #time.sleep(2)
        if 'milestone_name' in issue:
          issue['milestone'] = self.project.get_milestones()[ issue['milestone_name'] ]
          del issue['milestone_name']


        self.convert_relationships_to_comments(issue)

        issue['body'] = self._replace_jira_with_github_id(issue['body'])
        issue_comments = issue['comments']
        del issue['comments']
        comments = []
        for comment in issue_comments:
          comments.append(dict((k,self._replace_jira_with_github_id(v)) for k,v in comment.items()))

        self.import_issue_with_comments(issue, comments)

  def import_issue_with_comments(self, issue, comments):
    """
    Imports a single issue with its comments into GitHub.
    Importing via GitHub's normal Issue API quickly triggers anti-abuse rate limits.
    So their unofficial Issue Import API is used instead:
    https://gist.github.com/jonmagic/5282384165e0f86ef105
    This is a two-step process:
    First the issue with the comments is pushed to GitHub asynchronously.
    Then GitHub is pulled in a loop until the issue import is completed.
    Finally the issue github is noted.    
    """

    # bl: reset the array in case we have extra comments we need to create
    self.comments_to_append = []

    print 'Issue ', issue['key']
    jira_key = issue['key']
    del issue['key']
    headers = self.headers
    headers['Accept'] = 'application/vnd.github.golden-comet-preview+json'
    response = self.upload_github_issue(issue, comments, headers)
    status_url = response.json()['url']
    gh_issue_url = self.wait_for_issue_creation(status_url, headers).json()['issue_url']
    gh_issue_id = int(gh_issue_url.split('/')[-1])
    jira_num = int(jira_key.split("-",1)[1])
    issue['key'] = jira_key
    if jira_num != gh_issue_id:
        print 'Failed creating JIRA issue ' + str(jira_key) + '. Created #' + str(gh_issue_id) + '. Trying again!'
        #  bl: if the issue wasn't created with the right ID, try again. probably a deleted/skipped issue.
        get_issue_url = self.github_url + '/issues/' + str(gh_issue_id)
        response = requests.get(get_issue_url, headers=self.headers, timeout=Importer._DEFAULT_TIME_OUT)
        if response.status_code != 200:
            raise RuntimeError(
                "Failed to get an issue we just created! unexpected HTTP status code: {}".format(response.status_code)
            )

        issue_json = response.json()
        self.delete_issue(str(issue_json['node_id']))
        self.import_issue_with_comments(issue, comments)
        return
    issue['githubid'] = gh_issue_id
    #print "\nGithub issue id: ", gh_issue_id

    # bl: now manually create any one-off comments
    for long_comment in self.comments_to_append:
        self.upload_extra_comment(gh_issue_id, issue, long_comment)
    
  def upload_github_issue(self, issue, comments, headers):
      """
      Uploads a single issue to GitHub asynchronously with the Issue Import API.
      """
      issue_url = self.github_url + '/import/issues'
      self.trim_long_issue_body(issue, comments)
      self.trim_payload_size(issue, comments)

      # print json.dumps(issue_data, indent=2, sort_keys=True)
      response = requests.post(issue_url, json=self.issue_data, headers=headers, timeout=Importer._DEFAULT_TIME_OUT)
      if response.status_code == 202:
          return response
      elif response.status_code == 422:
          raise RuntimeError(
              "Initial import validation failed for issue '{}' due to the "
              "following errors:\n{}".format(issue['title'], response.json())
          )
      else:
          raise RuntimeError(
              "Failed to POST issue: '{}' due to unexpected HTTP status code: {}\nerrors:\n{} \nURL {}"
              .format(issue['title'], response.status_code, response.json(), issue_url)
          )


  def wait_for_issue_creation(self, status_url, headers):
      """
      Check the status of a GitHub issue import.
      If the status is 'pending', it sleeps, then rechecks until the status is
      either 'imported' or 'failed'.
      """
      i = 0
      while True:  # keep checking until status is something other than 'pending'
          response = requests.get(status_url, headers=headers, timeout=Importer._DEFAULT_TIME_OUT)
          if response.status_code != 200:
              print "Failed to check GitHub issue import status url: {} due to unexpected HTTP status code: {}".format(status_url, response.status_code)
              i = i+1
              if i > 100:
                  raise RuntimeError("Failing import status check permanently!")
          else:
              status = response.json()['status']
              if status != 'pending':
                  break
          time.sleep(1)
      if status == 'imported':
          print "Imported Issue:", response.json()['issue_url']
      elif status == 'failed':
          print "Issue JSON: " + json.dumps(self.issue_data)
          raise RuntimeError(
              "Failed to import GitHub issue due to the following errors:\n{}"
              .format(response.json())
          )
      else:
          raise RuntimeError(
              "Status check for GitHub issue import returned unexpected status: '{}'"
              .format(status)
          )
      return response

  def trim_long_issue_body(self, issue, comments):
      body = issue['body']
      body_len = len(body)
      if body_len > 65536:
          n = 65436
          # bl: split the body into comments so that no data is lost
          chunks = [body[i:i+n] for i in range(0, len(body), n)]
          chunk_len = len(chunks)
          for i in range(chunk_len):
              chunk = chunks[i]
              chunk = '<i>issue chunk ' + str(i + 1) + ' of ' + str(chunk_len) + '</i>\n' + chunk
              # bl: the first chunk is the main issue body. the rest will be comments in order
              if i == 0:
                  issue['body'] = chunk
              else:
                  comments.insert(i-1, {'body': chunk, 'created_at': issue['created_at']})

  def trim_payload_size(self, issue, comments):
      # bl: find the lowest index of the comment that we need to remove and start inserting at the end. it will either be the first comment over 64KB
      # or it might be the first comment that brings the total issue size under 1MB
      # bl: start by trimming any comment that has a body over 64KB in length since that's not allowed
      comment_to_strip_from = None
      num_comments = len(comments)
      for i in range(num_comments):
          comment = comments[i]
          comment_len = len(comment['body'])
          if comment_len > 65536:
              comment_to_strip_from = i
              break

      # bl: work from the back forward until the issue_data body is less than 1MB
      for i in range(num_comments, 0, -1):
          self.issue_data = {'issue': issue, 'comments': comments[0:i]}
          # bl: once the body is under 1MB, we are done
          if len(json.dumps(self.issue_data)) <= 1048576:
              if i < num_comments:
                  comment_to_strip_from = max(comment_to_strip_from, i)
              break

      self.issue_data = {'issue': issue, 'comments': comments[0: comment_to_strip_from if comment_to_strip_from is not None else num_comments]}

      if comment_to_strip_from is not None:
          self.remove_comments_from(comments, comment_to_strip_from)

  def remove_comments_from(self, comments, index):
      # bl: to avoid indexing issues, work from the back of the list to the front
      for i in range(len(comments)-1, index-1, -1):
          removed_comment = comments[i]
          del comments[i]
          self.comments_to_append.insert(0, removed_comment)
          print 'Removed comment {}'.format(i)

  def upload_extra_comment(self, gh_issue_id, issue, comment):
      issue_comment_url = self.github_url + '/issues/' + str(gh_issue_id) + '/comments'

      headers = self.headers
      headers['Content-Type'] = 'application/json'

      body = comment['body']
      # bl: prepend the original comment date since it's going to be lost
      # bl: comments can be at most 65,536 characters. reduce by 100 so we can add the prefix for each chunk
      n = 65436
      # bl: split the long comment into multiple comments so that no data is lost
      chunks = [body[i:i+n] for i in range(0, len(body), n)]
      chunk_len = len(chunks)
      for i in range(chunk_len):
          chunk = chunks[i]
          # bl: identify if this is a comment or an extension of the issue body by the post time
          if issue['created_at'] != comment['created_at']:
              if i == 0:
                  chunk = '<i>originally posted at ' + comment['created_at'] + '</i>\n' + chunk
              if chunk_len > 1:
                  chunk = '<i>comment chunk ' + str(i + 1) + ' of ' + str(chunk_len) + '</i>\n' + chunk
          new_comment = {'body': chunk}

          response = requests.post(issue_comment_url, json=new_comment, headers=headers, timeout=Importer._DEFAULT_TIME_OUT)
          if response.status_code != 201:
              raise RuntimeError(
                  "Failed to post issue comment {} due to unexpected HTTP status code: {} ; text: {}".format(issue_comment_url, response.status_code, response.text)
              )
      print 'Appended {} comments for comment in issue #{}'.format(len(chunks), gh_issue_id)

  def convert_relationships_to_comments(self, issue):
    duplicates = issue['duplicates']
    is_duplicated_by = issue['is-duplicated-by']
    requires = issue['requires']
    is_required_by = issue['is-required-by']
    caused = issue['caused']
    is_caused_by = issue['is-caused-by']
    incorporates = issue['incorporates']
    is_incorporateed_by = issue['is-incorporated-by']
    relates_to = issue['relates-to']
    is_related_to = issue['is-related-to']
    depends_on = issue['depends-on']
    blocks = issue['blocks']

    for duplicate_item in duplicates:
      self._add_link_to_issue(issue, "Duplicates: " + self._replace_jira_with_github_id(duplicate_item))

    for is_duplicated_by_item in is_duplicated_by:
      self._add_link_to_issue(issue, "Is duplicated by: " + self._replace_jira_with_github_id(is_duplicated_by_item))

    for require_item in requires:
      self._add_link_to_issue(issue, "Requires: " + self._replace_jira_with_github_id(require_item))

    for is_required_by_item in is_required_by:
      self._add_link_to_issue(issue, "Is required by: " + self._replace_jira_with_github_id(is_required_by_item))

    for caused_item in caused:
      self._add_link_to_issue(issue, "Caused: " + self._replace_jira_with_github_id(caused_item))

    for is_caused_by_item in is_caused_by:
      self._add_link_to_issue(issue, "Is caused by: " + self._replace_jira_with_github_id(is_caused_by_item))

    for incorporates_item in incorporates:
      self._add_link_to_issue(issue, "Caused: " + self._replace_jira_with_github_id(incorporates_item))

    for is_incorporated_by_item in is_incorporateed_by:
      self._add_link_to_issue(issue, "Is caused by: " + self._replace_jira_with_github_id(is_incorporated_by_item))

    for relates_to_item in relates_to:
      self._add_link_to_issue(issue, "Relates to: " + self._replace_jira_with_github_id(relates_to_item))

    for is_related_to_item in is_related_to:
      self._add_link_to_issue(issue, "Is related to: " + self._replace_jira_with_github_id(is_related_to_item))

    for depends_on_item in depends_on:
      self._add_link_to_issue(issue, "Depends on: " + self._replace_jira_with_github_id(depends_on_item))

    for blocks_item in blocks:
      self._add_link_to_issue(issue, "Blocks: " + self._replace_jira_with_github_id(blocks_item))

    del issue['duplicates']
    del issue['is-duplicated-by']
    del issue['requires']
    del issue['is-required-by']
    del issue['caused']
    del issue['is-caused-by']
    del issue['incorporates']
    del issue['is-incorporated-by']
    del issue['relates-to']
    del issue['is-related-to']
    del issue['depends-on']
    del issue['blocks']

  def _add_link_to_issue(self, issue, body):
      issue['comments'].insert(0, {"created_at": issue["created_at"], "body": body})

  def _replace_jira_urls_for_github(self, text):
    result = text
    for pattern, replacement in self.jira_issue_url_replace_patterns.iteritems():
      result = re.sub(pattern, replacement, result)
    return result

  def _replace_jira_with_github_id(self, text):
    result = text
    for pattern, replacement in self.jira_issue_replace_patterns.iteritems():
      result = re.sub(pattern, Importer._PLACEHOLDER_PREFIX + replacement + Importer._PLACEHOLDER_SUFFIX, result)
    return self._replace_jira_urls_for_github(result)
      
  def post_process_comments(self):
    """
    Starts post-processing all issue comments.
    """
    comment_url = self.github_url + '/issues/comments'
    self._post_process_comments(comment_url) 
    
  def _post_process_comments(self, url):
    """
    Paginates through all issue comments and replaces the issue id placeholders with the correct issue ids.
    """    
    print "listing comments using " + url
    response = requests.get(url, headers=self.headers, timeout=Importer._DEFAULT_TIME_OUT)
    if response.status_code != 200:
        raise RuntimeError(
            "Failed to list all comments due to unexpected HTTP status code: {}".format(response.status_code)
        )
      
    comments = response.json()
    for comment in comments:
      # print "handling comment " + comment['url']
      body = comment['body']
      if Importer._PLACEHOLDER_PREFIX in body:
        newbody = self._replace_github_id_placholder(body)
        self._patch_comment(comment['url'], newbody)
    try:
      next_comments = response.links["next"]
      if next_comments:
        next_url = next_comments['url']
        self._post_process_comments(next_url)
    except KeyError:
      print 'no more pages for comments: '
      for key, value in response.links.items():
        print(key)
        print(value)

  def _replace_github_id_placholder(self, text):
    result = text
    pattern = Importer._PLACEHOLDER_PREFIX + r'(\d+)' + Importer._PLACEHOLDER_SUFFIX
    result = re.sub(pattern, r'#\1', result)
    return result

  def _patch_comment(self, url, body):
    """
    Patches a single comment body of a Github issue.
    """
    print "patching comment " + url
    # print "new body:" + body
    patch_data = {'body': body}
    # print patch_data
    response = requests.patch(url, json=patch_data, headers=self.headers, timeout=Importer._DEFAULT_TIME_OUT)
    if response.status_code != 200:
        raise RuntimeError(
            "Failed to patch comment {} due to unexpected HTTP status code: {} ; text: {}".format(url, response.status_code, response.text)
        )

  def purge_existing_issues(self):
    print "Calling graphql api..."

    
    headers = self.headers
    headers['Content-Type'] = 'application/json'

    q = """
    {
      __typename
      search(type: ISSUE, query: "repo:""" + self.options.account + '/' + self.options.repo + """", first: 100) {
        nodes {
          ... on Issue {
            id
          }
        }
      }
    }
    """

    print 'query: {}'.format(q)
    response = requests.post(self.githubGQL_url, headers=headers, json={'query': q})
    if response.status_code != 200:
      raise RuntimeError(
            "Failed to get issues {} due to unexpected HTTP status code: {} ; text: {}".format(self.githubGQL_url, response.status_code, response.text)
          )
    else:
      data = response.json()
      
      for node in data['data']['search']['nodes'] :
          self.delete_issue_with_headers(node['id'], headers)

  def delete_issue(self, id):
    headers = self.headers
    headers['Content-Type'] = 'application/json'
    self.delete_issue_with_headers(id, headers)

  def delete_issue_with_headers(self, id, headers):
      d = """
          mutation {   deleteIssue(input: {issueId: \"""" + id + """\"}) {     clientMutationId    repository {      id    }  }}
          """
      print 'query: {}'.format(d)

      response = requests.post(self.githubGQL_url, headers=headers, json={'query': d})
      if response.status_code != 200:
        raise RuntimeError(
              "Failed to get issues {} due to unexpected HTTP status code: {} ; text: {}".format(self.githubGQL_url, response.status_code, response.text)
            )
      else:
        print response.json()
